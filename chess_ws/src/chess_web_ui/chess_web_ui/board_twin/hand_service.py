"""Side-view hand detection service (YOLO)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from chess_web_ui.board_twin.calibration import SideViewCalibration
from chess_web_ui.board_twin.hand_presence import (
    HandDetection,
    HandPresenceConfig,
    HandPresenceTracker,
    HandPresenceUpdate,
    filter_detections_in_board,
)
from chess_web_ui.board_twin.paths import resolve_hand_model_path


@dataclass
class HandServiceConfig:
    model_path: str
    calibration_path: str
    conf_threshold: float = 0.35
    iou_threshold: float = 0.5
    imgsz: int = 640
    device: str = ''
    board_margin_px: float = 20.0
    present_frames: int = 3
    absent_frames: int = 4


class HandDetectorService:
    """YOLO hand detector with board ROI presence tracking."""

    def __init__(self, config: HandServiceConfig) -> None:
        self.config = config
        self.calibration = SideViewCalibration.from_json_file(config.calibration_path)
        self._detector: Any | None = None
        self._tracker = HandPresenceTracker(
            HandPresenceConfig(
                present_frames=config.present_frames,
                absent_frames=config.absent_frames,
                board_margin_px=config.board_margin_px,
            )
        )

    def _ensure_detector(self) -> Any:
        if self._detector is not None:
            return self._detector
        from chess_piece_classifier.chess_detector import ChessPieceDetector

        model_path = resolve_hand_model_path(self.config.model_path)
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

    def reload_calibration(self) -> None:
        self.calibration = SideViewCalibration.from_json_file(self.config.calibration_path)

    def detect_raw(self, bgr_image: np.ndarray) -> list[Any]:
        if bgr_image is None or bgr_image.size == 0:
            return []
        detector = self._ensure_detector()
        return detector.detect(bgr_image)

    def update_from_frame(self, bgr_image: np.ndarray) -> HandPresenceUpdate:
        raw = self.detect_raw(bgr_image)
        mapped = filter_detections_in_board(
            raw,
            self.calibration.board_corners,
            margin_px=self.config.board_margin_px,
        )
        return self._tracker.update(mapped)

    def annotate_frame(
        self,
        bgr_image: np.ndarray,
        detections: list[HandDetection] | None = None,
    ) -> np.ndarray:
        import cv2

        annotated = bgr_image.copy()
        dets = detections if detections is not None else self._tracker._last_detections
        for det in dets:
            x1, y1, x2, y2 = map(int, det.bbox)
            color = (0, 0, 255) if det.in_board_roi else (0, 165, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f'{det.class_name} {det.score:.2f}'
            cv2.putText(
                annotated,
                label,
                (x1, max(0, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA,
            )
        return annotated

    @property
    def tracker(self) -> HandPresenceTracker:
        return self._tracker
