"""Chess board corner detection and homography helpers."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class BoardDetectionResult:
    success: bool
    message: str
    corners_image: list[tuple[float, float]] | None = None


class BoardDetector:
    """Map image pixels to board square coordinates (col 0-7, row 0-7)."""

    def __init__(self, inner_cols: int = 7, inner_rows: int = 7, flip_files: bool = False) -> None:
        self.inner_cols = inner_cols
        self.inner_rows = inner_rows
        self.flip_files = flip_files
        self.image_to_board: np.ndarray | None = None
        self.board_to_image: np.ndarray | None = None
        self.is_calibrated = False
        self.corners_image: list[tuple[float, float]] | None = None

    def board_to_image_coords(self, board_x: float, board_y: float) -> tuple[float, float]:
        if self.board_to_image is None:
            raise RuntimeError('board not calibrated')
        pt = np.array([[[board_x, board_y]]], dtype=np.float32)
        img_pt = cv2.perspectiveTransform(pt, self.board_to_image)[0][0]
        return float(img_pt[0]), float(img_pt[1])

    def warp_to_board(
        self,
        image: np.ndarray,
        size: int = 800,
        interpolation: int = cv2.INTER_LINEAR,
    ) -> np.ndarray:
        if self.board_to_image is None:
            raise RuntimeError('board not calibrated')
        dst = np.array(
            [[[0, 0]], [[size - 1, 0]], [[size - 1, size - 1]], [[0, size - 1]]],
            dtype=np.float32,
        )
        src = np.array(
            [
                self.board_to_image_coords(0.0, 0.0),
                self.board_to_image_coords(8.0, 0.0),
                self.board_to_image_coords(8.0, 8.0),
                self.board_to_image_coords(0.0, 8.0),
            ],
            dtype=np.float32,
        ).reshape(4, 1, 2)
        matrix = cv2.getPerspectiveTransform(src, dst)
        return cv2.warpPerspective(image, matrix, (size, size), flags=interpolation)

    def detect_corners(
        self,
        image: np.ndarray,
        manual_corners: list[float] | None = None,
    ) -> BoardDetectionResult:
        if image is None or image.size == 0:
            return BoardDetectionResult(False, 'empty image')

        if manual_corners and len(manual_corners) == 8:
            corners = self._manual_corners(manual_corners)
            self._set_homography(corners)
            return BoardDetectionResult(True, 'manual corners', corners)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
        found, inner_corners = False, None
        if hasattr(cv2, 'findChessboardCornersSB'):
            found, inner_corners = cv2.findChessboardCornersSB(
                gray,
                (self.inner_cols, self.inner_rows),
                flags,
            )
        if not found:
            found, inner_corners = cv2.findChessboardCorners(
                gray,
                (self.inner_cols, self.inner_rows),
                flags,
            )
        if not found or inner_corners is None:
            return BoardDetectionResult(False, 'chessboard corners not found')

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        inner_corners = cv2.cornerSubPix(
            gray,
            inner_corners,
            winSize=(11, 11),
            zeroZone=(-1, -1),
            criteria=criteria,
        )
        corners = self._outer_corners_from_inner(inner_corners)
        self._set_homography(corners)
        return BoardDetectionResult(True, 'detected chessboard corners', corners)

    def compute_homography(self, corners: list[tuple[float, float]]) -> np.ndarray | None:
        if len(corners) != 4:
            return None
        self._set_homography(corners)
        return self.image_to_board

    def image_to_square(self, x: float, y: float) -> tuple[int, int] | None:
        if self.image_to_board is None:
            return None
        pt = np.array([[[x, y]]], dtype=np.float32)
        board_pt = cv2.perspectiveTransform(pt, self.image_to_board)[0][0]
        col = int(np.clip(np.floor(board_pt[0]), 0, 7))
        row = int(np.clip(np.floor(board_pt[1]), 0, 7))
        return col, row

    def is_point_in_board(self, x: float, y: float, margin: float = 0.0) -> bool:
        if self.corners_image is None or len(self.corners_image) != 4:
            return False
        polygon = np.array(self.corners_image, dtype=np.float32)
        return cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= margin

    def draw_board_roi(self, image: np.ndarray, color: tuple[int, int, int] = (0, 255, 255)) -> np.ndarray:
        if self.corners_image is None:
            return image
        annotated = image.copy()
        pts = np.array(self.corners_image, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=2)
        return annotated

    def draw_board_grid(self, image: np.ndarray) -> np.ndarray:
        if self.board_to_image is None:
            return image

        annotated = image.copy()
        for row in range(8):
            for col in range(8):
                center_board = np.array([[[col + 0.5, row + 0.5]]], dtype=np.float32)
                center_img = cv2.perspectiveTransform(center_board, self.board_to_image)[0][0]
                cx, cy = int(center_img[0]), int(center_img[1])
                cv2.circle(annotated, (cx, cy), 4, (255, 0, 0), -1)
                cv2.putText(
                    annotated,
                    f'{chr(ord("a") + col)}{row + 1}',
                    (cx + 4, cy - 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (255, 0, 0),
                    1,
                    cv2.LINE_AA,
                )
        return annotated

    def _manual_corners(self, values: list[float]) -> list[tuple[float, float]]:
        return [
            (values[0], values[1]),
            (values[2], values[3]),
            (values[4], values[5]),
            (values[6], values[7]),
        ]

    def _outer_corners_from_inner(
        self,
        inner_corners: np.ndarray,
    ) -> list[tuple[float, float]]:
        grid = inner_corners.reshape(self.inner_rows, self.inner_cols, 2)

        def extrapolate(p1: np.ndarray, p2: np.ndarray) -> tuple[float, float]:
            vec = p2 - p1
            point = p1 - vec
            return float(point[0]), float(point[1])

        tl = extrapolate(grid[1, 0], grid[0, 0])
        tr = extrapolate(grid[1, -1], grid[0, -1])
        br = extrapolate(grid[-2, -1], grid[-1, -1])
        bl = extrapolate(grid[-2, 0], grid[-1, 0])
        return [tl, tr, br, bl]

    def _set_homography(self, image_corners: list[tuple[float, float]]) -> None:
        src = np.array(image_corners, dtype=np.float32)
        if self.flip_files:
            dst = np.array(
                [
                    [8.0, 0.0],
                    [0.0, 0.0],
                    [0.0, 8.0],
                    [8.0, 8.0],
                ],
                dtype=np.float32,
            )
        else:
            dst = np.array(
                [
                    [0.0, 0.0],
                    [8.0, 0.0],
                    [8.0, 8.0],
                    [0.0, 8.0],
                ],
                dtype=np.float32,
            )
        self.board_to_image = cv2.getPerspectiveTransform(dst, src)
        self.image_to_board = cv2.getPerspectiveTransform(src, dst)
        self.corners_image = list(image_corners)
        self.is_calibrated = True
