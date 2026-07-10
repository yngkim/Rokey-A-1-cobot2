"""Side-view webcam capture and YOLO inference service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from chess_web_ui.board_twin.calibration import SideViewCalibration
from chess_web_ui.board_twin.normalizer import normalize_side_detections
from chess_web_ui.board_twin.paths import resolve_side_model_path
from chess_web_ui.board_twin.types import SideDetectionView, SideViewBoardEstimate
from chess_web_ui.board_twin.webcam_capture import PersistentWebcamCapture


@dataclass
class SideServiceConfig:
    model_path: str
    calibration_path: str
    conf_threshold: float = 0.15
    iou_threshold: float = 0.5
    imgsz: int = 640
    device: str = ''
    webcam_fps: int = 30


def draw_calibration_overlay(
    bgr_image: np.ndarray,
    corners: list[tuple[float, float]],
) -> np.ndarray:
    import cv2

    if len(corners) != 4:
        return bgr_image
    annotated = bgr_image.copy()
    labels = ['a1', 'h1', 'h8', 'a8']
    pts = [tuple(map(int, pt)) for pt in corners]
    for idx, (x, y) in enumerate(pts):
        cv2.circle(annotated, (x, y), 6, (0, 255, 255), -1)
        cv2.putText(
            annotated,
            labels[idx],
            (x + 8, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
    for i in range(4):
        cv2.line(annotated, pts[i], pts[(i + 1) % 4], (0, 200, 255), 2)
    return annotated


def annotate_with_squares(
    bgr_image: np.ndarray,
    detections: list[SideDetectionView],
) -> np.ndarray:
    """Draw bbox + piece@square labels on a copy of the frame."""
    import cv2

    annotated = bgr_image.copy()
    for view in detections:
        if view.bbox[2] > view.bbox[0] and view.bbox[3] > view.bbox[1]:
            x1, y1, x2, y2 = map(int, view.bbox)
        else:
            cx, cy = int(view.center_x), int(view.center_y)
            x1, y1, x2, y2 = cx - 20, cy - 20, cx + 20, cy + 20
        if view.symbol and view.square:
            label = f'{view.symbol}@{view.square} {view.confidence:.2f}'
        else:
            label = f'{view.class_name} {view.confidence:.2f}'
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            annotated,
            label,
            (x1, max(0, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )
    return annotated


class BoardTwinSideService:
    """Request/response side camera inference (independent from ROS nodes)."""

    def __init__(self, config: SideServiceConfig) -> None:
        self.config = config
        self.calibration = SideViewCalibration.from_json_file(config.calibration_path)
        self._detector: Any | None = None
        self._webcam: PersistentWebcamCapture | None = None

    def _ensure_detector(self) -> Any:
        if self._detector is not None:
            return self._detector
        from chess_piece_classifier.chess_detector import ChessPieceDetector

        model_path = resolve_side_model_path(self.config.model_path)
        self._detector = ChessPieceDetector(
            model_path=model_path,
            conf=self.config.conf_threshold,
            iou=self.config.iou_threshold,
            imgsz=self.config.imgsz,
            device=self.config.device,
        )
        self._detector.set_multi_pass(False)
        self._detector.set_preprocess(False)
        return self._detector

    def _get_webcam(self) -> PersistentWebcamCapture:
        device = self.calibration.webcam_device
        if self._webcam is None or self._webcam.preferred_device != device:
            if self._webcam is not None:
                self._webcam.release()
            self._webcam = PersistentWebcamCapture(
                device_id=device,
                width=self.calibration.camera_width,
                height=self.calibration.camera_height,
                fps=self.config.webcam_fps,
            )
        return self._webcam

    def capture_webcam_frame(self) -> np.ndarray | None:
        return self._get_webcam().read()

    def webcam_last_error(self) -> str:
        if self._webcam is None:
            return ''
        return self._webcam.last_error

    def release(self) -> None:
        if self._webcam is not None:
            self._webcam.release()
            self._webcam = None

    def detect_from_image(
        self,
        bgr_image: np.ndarray,
        *,
        recorded_fen: str = '',
    ) -> SideViewBoardEstimate:
        detector = self._ensure_detector()
        detections = detector.detect(bgr_image)
        mapper = self.calibration.build_mapper()
        return normalize_side_detections(detections, mapper, recorded_fen=recorded_fen)

    def detect_from_webcam(self, *, recorded_fen: str = '') -> tuple[SideViewBoardEstimate | None, str]:
        estimate, _, _annotated, msg = self.detect_and_annotate_from_webcam(recorded_fen=recorded_fen)
        if estimate is None:
            return None, msg
        return estimate, msg

    def detect_and_annotate_from_frame(
        self,
        frame: np.ndarray,
        *,
        recorded_fen: str = '',
    ) -> tuple[SideViewBoardEstimate | None, list[Any], np.ndarray | None, str]:
        if frame is None or frame.size == 0:
            return None, [], None, 'empty sideview frame'
        detector = self._ensure_detector()
        raw_detections = detector.detect(frame)
        mapper = self.calibration.build_mapper()
        estimate = normalize_side_detections(raw_detections, mapper, recorded_fen=recorded_fen)
        annotated = annotate_with_squares(frame, estimate.detections)
        annotated = draw_calibration_overlay(annotated, self.calibration.board_corners)
        return estimate, raw_detections, annotated, estimate.message

    def detect_and_annotate_from_webcam(
        self,
        *,
        recorded_fen: str = '',
    ) -> tuple[SideViewBoardEstimate | None, list[Any], np.ndarray | None, str]:
        frame = self.capture_webcam_frame()
        if frame is None:
            err = self.webcam_last_error() or 'side webcam capture failed'
            return None, [], None, err
        return self.detect_and_annotate_from_frame(frame, recorded_fen=recorded_fen)

    def detect_from_image_path(
        self,
        image_path: str | Path,
        *,
        recorded_fen: str = '',
    ) -> SideViewBoardEstimate:
        import cv2

        frame = cv2.imread(str(image_path))
        if frame is None or frame.size == 0:
            raise FileNotFoundError(f'could not read image: {image_path}')
        return self.detect_from_image(frame, recorded_fen=recorded_fen)
