"""Build board occupancy from YOLO detections and board homography."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from chess_board_detector.board_detector import BoardDetector
from chess_occupancy.depth_reference import cell_medians_from_warped_depth
from chess_piece_classifier.chess_detector import ChessPieceDetector, PieceDetection


@dataclass
class ScanResult:
    cells: list[bool]
    confidence: list[float]
    detections: list[PieceDetection]
    board_detected: bool
    message: str
    warped_debug: np.ndarray | None = field(default=None)
    depth_debug: np.ndarray | None = field(default=None)


def detections_to_occupancy(
    board_detector: BoardDetector,
    detections: list[PieceDetection],
) -> tuple[list[bool], list[float]]:
    cells = [False] * 64
    confidence = [0.0] * 64

    for det in detections:
        square = board_detector.image_to_square(det.center[0], det.center[1])
        if square is None:
            continue
        col, row = square
        idx = row * 8 + col
        if det.score >= confidence[idx]:
            cells[idx] = True
            confidence[idx] = det.score

    return cells, confidence


def detections_to_occupancy_warped(
    detections: list[PieceDetection],
    warp_size: int,
) -> tuple[list[bool], list[float]]:
    """Map detections on a top-down warped board image to 64 cells."""
    cells = [False] * 64
    confidence = [0.0] * 64
    cell_size = warp_size / 8.0

    for det in detections:
        col = int(np.clip(det.center[0] / cell_size, 0, 7))
        row = int(np.clip(det.center[1] / cell_size, 0, 7))
        idx = row * 8 + col
        if det.score >= confidence[idx]:
            cells[idx] = True
            confidence[idx] = det.score

    return cells, confidence


def heuristic_occupancy_warped(
    warped_bgr: np.ndarray,
    warp_size: int,
) -> tuple[list[bool], list[float]]:
    """Per-cell edge/variance heuristic for pieces YOLO misses (esp. white on light squares)."""
    import cv2

    gray = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2GRAY)
    cell_px = warp_size / 8.0
    margin_ratio = 0.22
    cells = [False] * 64
    confidence = [0.0] * 64

    for row in range(8):
        for col in range(8):
            x1 = int(col * cell_px + cell_px * margin_ratio)
            y1 = int(row * cell_px + cell_px * margin_ratio)
            x2 = int((col + 1) * cell_px - cell_px * margin_ratio)
            y2 = int((row + 1) * cell_px - cell_px * margin_ratio)
            patch = gray[y1:y2, x1:x2]
            if patch.size == 0:
                continue

            lap_var = float(cv2.Laplacian(patch, cv2.CV_64F).var())
            mean_val = float(patch.mean())
            is_light_square = (row + col) % 2 == 1
            if is_light_square:
                threshold = 42.0 if mean_val > 130.0 else 70.0
            else:
                threshold = 85.0

            idx = row * 8 + col
            score = min(lap_var / max(threshold * 2.5, 1.0), 1.0)
            if lap_var >= threshold:
                cells[idx] = True
                confidence[idx] = score

    return cells, confidence


def depth_occupancy_warped(
    warped_depth: np.ndarray,
    empty_cell_medians: np.ndarray,
    warp_size: int,
    threshold_mm: float = 4.0,
    min_conf: float = 0.30,
) -> tuple[list[bool], list[float], np.ndarray]:
    """Mark cells occupied when depth is closer than empty-board reference."""
    import cv2

    current_medians = cell_medians_from_warped_depth(warped_depth, warp_size)
    cells = [False] * 64
    confidence = [0.0] * 64
    diff_grid = np.zeros((8, 8), dtype=np.float32)

    for row in range(8):
        for col in range(8):
            empty = empty_cell_medians[row, col]
            current = current_medians[row, col]
            if np.isnan(empty) or np.isnan(current):
                continue
            delta = float(empty - current)
            diff_grid[row, col] = max(delta, 0.0)
            if delta < threshold_mm:
                continue
            idx = row * 8 + col
            cells[idx] = True
            confidence[idx] = min(delta / max(threshold_mm * 3.0, 1.0), 1.0)
            if confidence[idx] < min_conf:
                cells[idx] = False
                confidence[idx] = 0.0

    diff_norm = np.clip(diff_grid / max(threshold_mm * 2.0, 1.0), 0.0, 1.0)
    diff_u8 = (diff_norm * 255.0).astype(np.uint8)
    heatmap = cv2.applyColorMap(diff_u8, cv2.COLORMAP_TURBO)
    cell_px = max(warp_size // 8, 1)
    depth_debug = cv2.resize(
        heatmap,
        (cell_px * 8, cell_px * 8),
        interpolation=cv2.INTER_NEAREST,
    )
    return cells, confidence, depth_debug


def merge_occupancy(
    primary_cells: list[bool],
    primary_conf: list[float],
    fallback_cells: list[bool],
    fallback_conf: list[float],
    *,
    fallback_min_conf: float = 0.30,
) -> tuple[list[bool], list[float]]:
    cells = list(primary_cells)
    confidence = list(primary_conf)
    for idx in range(64):
        if cells[idx]:
            continue
        if fallback_cells[idx] and fallback_conf[idx] >= fallback_min_conf:
            cells[idx] = True
            confidence[idx] = fallback_conf[idx]
    return cells, confidence


def filter_detections_in_board_roi(
    board_detector: BoardDetector,
    detections: list[PieceDetection],
) -> list[PieceDetection]:
    if not board_detector.is_calibrated:
        return detections
    return [
        det
        for det in detections
        if board_detector.is_point_in_board(det.center[0], det.center[1])
    ]


def _warp_pixel_to_board(px: float, py: float, warp_size: int) -> tuple[float, float]:
    return px / warp_size * 8.0, py / warp_size * 8.0


def _is_on_board(board_x: float, board_y: float, margin: float = 0.15) -> bool:
    return -margin <= board_x <= 8.0 + margin and -margin <= board_y <= 8.0 + margin


def map_warped_detections_to_image(
    board_detector: BoardDetector,
    detections: list[PieceDetection],
    warp_size: int,
) -> list[PieceDetection]:
    """Project warped-board YOLO boxes back onto the original camera image."""
    mapped: list[PieceDetection] = []
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        warp_corners = (
            (x1, y1),
            (x2, y1),
            (x2, y2),
            (x1, y2),
        )
        image_corners: list[tuple[float, float]] = []
        board_centers: list[tuple[float, float]] = []
        for wx, wy in warp_corners:
            bx, by = _warp_pixel_to_board(wx, wy, warp_size)
            board_centers.append((bx, by))
            image_corners.append(board_detector.board_to_image_coords(bx, by))

        center_bx = sum(b[0] for b in board_centers) / 4.0
        center_by = sum(b[1] for b in board_centers) / 4.0
        if not _is_on_board(center_bx, center_by):
            continue

        xs = [p[0] for p in image_corners]
        ys = [p[1] for p in image_corners]
        center_x = sum(xs) / 4.0
        center_y = sum(ys) / 4.0
        mapped.append(
            PieceDetection(
                bbox=(min(xs), min(ys), max(xs), max(ys)),
                center=(center_x, center_y),
                score=det.score,
                class_id=det.class_id,
                class_name=det.class_name,
                polygon=tuple(image_corners),
            )
        )

    mapped = filter_detections_in_board_roi(board_detector, mapped)
    return filter_detections_for_display(board_detector, mapped)


def filter_detections_for_display(
    board_detector: BoardDetector,
    detections: list[PieceDetection],
) -> list[PieceDetection]:
    """Keep the highest-score detection per board cell for cleaner overlays."""
    by_cell: dict[int, PieceDetection] = {}
    for det in detections:
        square = board_detector.image_to_square(det.center[0], det.center[1])
        if square is None:
            continue
        col, row = square
        idx = row * 8 + col
        prev = by_cell.get(idx)
        if prev is None or det.score >= prev.score:
            by_cell[idx] = det
    return list(by_cell.values())


def _scan_warped(
    bgr_image: np.ndarray,
    board_detector: BoardDetector,
    piece_detector: ChessPieceDetector,
    *,
    warp_size: int,
    heuristic_fallback: bool,
    depth_image: np.ndarray | None = None,
    empty_depth_reference: np.ndarray | None = None,
    depth_threshold_mm: float = 4.0,
    depth_min_conf: float = 0.30,
    depth_occupancy_enabled: bool = True,
    yolo_enabled: bool = True,
) -> ScanResult:
    import cv2

    warped = board_detector.warp_to_board(bgr_image, warp_size)
    detections_warped: list[PieceDetection] = []
    yolo_cells = [False] * 64
    yolo_conf = [0.0] * 64
    if yolo_enabled:
        detections_warped = piece_detector.detect(warped)
        yolo_cells, yolo_conf = detections_to_occupancy_warped(detections_warped, warp_size)

    depth_debug = None
    depth_cells: list[bool] | None = None
    depth_conf: list[float] | None = None
    use_depth = (
        depth_occupancy_enabled
        and depth_image is not None
        and empty_depth_reference is not None
    )
    if use_depth:
        warped_depth = board_detector.warp_to_board(
            depth_image,
            warp_size,
            interpolation=cv2.INTER_NEAREST,
        )
        depth_cells, depth_conf, depth_debug = depth_occupancy_warped(
            warped_depth,
            empty_depth_reference,
            warp_size,
            threshold_mm=depth_threshold_mm,
            min_conf=depth_min_conf,
        )
        cells, confidence = depth_cells, depth_conf
        if yolo_enabled:
            cells, confidence = merge_occupancy(
                cells,
                confidence,
                yolo_cells,
                yolo_conf,
                fallback_min_conf=0.25,
            )
    elif yolo_enabled:
        cells, confidence = yolo_cells, yolo_conf
        if heuristic_fallback:
            h_cells, h_conf = heuristic_occupancy_warped(warped, warp_size)
            cells, confidence = merge_occupancy(cells, confidence, h_cells, h_conf)
    else:
        cells, confidence = [False] * 64, [0.0] * 64

    detections = (
        map_warped_detections_to_image(board_detector, detections_warped, warp_size)
        if yolo_enabled
        else []
    )
    occupied = sum(cells)
    depth_count = sum(depth_cells) if depth_cells is not None else 0
    mode = 'depth' if use_depth else ('yolo' if yolo_enabled else 'none')
    return ScanResult(
        cells=cells,
        confidence=confidence,
        detections=detections,
        board_detected=True,
        message=f'{occupied}/64 occupied, {mode}={depth_count if use_depth else len(detections_warped)}',
        warped_debug=None,
        depth_debug=depth_debug,
    )


def scan_board(
    bgr_image: np.ndarray,
    board_detector: BoardDetector,
    piece_detector: ChessPieceDetector,
    manual_corners: list[float] | None = None,
    *,
    warp_board: bool = True,
    warp_size: int = 800,
    heuristic_fallback: bool = True,
    depth_image: np.ndarray | None = None,
    empty_depth_reference: np.ndarray | None = None,
    depth_threshold_mm: float = 4.0,
    depth_min_conf: float = 0.30,
    depth_occupancy_enabled: bool = True,
    yolo_enabled: bool = True,
) -> ScanResult:
    board_result = board_detector.detect_corners(bgr_image, manual_corners)
    if not board_result.success:
        detections = (
            piece_detector.detect(bgr_image)
            if yolo_enabled
            else []
        )
        detections = filter_detections_in_board_roi(board_detector, detections)
        return ScanResult(
            cells=[False] * 64,
            confidence=[0.0] * 64,
            detections=detections,
            board_detected=False,
            message=(
                f'{board_result.message} (yolo_raw={len(detections)}). '
                'Set board_manual_corners in vision_realsense_params.yaml'
            ),
        )

    if warp_board:
        return _scan_warped(
            bgr_image,
            board_detector,
            piece_detector,
            warp_size=warp_size,
            heuristic_fallback=heuristic_fallback,
            depth_image=depth_image,
            empty_depth_reference=empty_depth_reference,
            depth_threshold_mm=depth_threshold_mm,
            depth_min_conf=depth_min_conf,
            depth_occupancy_enabled=depth_occupancy_enabled,
            yolo_enabled=yolo_enabled,
        )

    detections = piece_detector.detect(bgr_image) if yolo_enabled else []
    detections = filter_detections_in_board_roi(board_detector, detections)
    cells, confidence = detections_to_occupancy(board_detector, detections)
    detections = filter_detections_for_display(board_detector, detections)
    occupied = sum(cells)
    return ScanResult(
        cells=cells,
        confidence=confidence,
        detections=detections,
        board_detected=True,
        message=f'{occupied}/64 occupied',
    )
