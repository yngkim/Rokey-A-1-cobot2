"""Board ROI hand presence tracking with debounced state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HandPresenceState(str, Enum):
    ABSENT = 'absent'
    PRESENT = 'present'


@dataclass
class HandDetection:
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    score: float
    class_name: str = 'hand'
    in_board_roi: bool = False


@dataclass
class HandPresenceConfig:
    present_frames: int = 3
    absent_frames: int = 8
    board_margin_px: float = 20.0


@dataclass
class HandPresenceUpdate:
    state: HandPresenceState
    hand_in_board: bool
    hand_seen: bool
    hand_present: bool
    entered_board: bool = False
    left_board: bool = False
    detections: list[HandDetection] = field(default_factory=list)


def _point_in_board_roi(
    x: float,
    y: float,
    corners: list[tuple[float, float]],
    margin_px: float,
) -> bool:
    if len(corners) != 4:
        return False
    import cv2
    import numpy as np

    pts = np.array(corners, dtype=np.float32)
    if margin_px > 0:
        cx = float(np.mean(pts[:, 0]))
        cy = float(np.mean(pts[:, 1]))
        scale = 1.0 + margin_px / max(1.0, min(np.linalg.norm(pts[1] - pts[0]), np.linalg.norm(pts[3] - pts[0])))
        pts = np.array(
            [
                [cx + (px - cx) * scale, cy + (py - cy) * scale]
                for px, py in pts
            ],
            dtype=np.float32,
        )
    return cv2.pointPolygonTest(pts, (float(x), float(y)), False) >= 0


def filter_detections_in_board(
    detections: list[Any],
    board_corners: list[tuple[float, float]],
    *,
    margin_px: float = 20.0,
) -> list[HandDetection]:
    """Map raw YOLO detections to HandDetection with board ROI flag."""
    out: list[HandDetection] = []
    for det in detections:
        if hasattr(det, 'bbox'):
            bbox = tuple(float(v) for v in det.bbox)
            center = tuple(float(v) for v in det.center)
            score = float(det.score)
            class_name = str(getattr(det, 'class_name', 'hand'))
        else:
            bbox = tuple(float(v) for v in det['bbox'])
            center = tuple(float(v) for v in det['center'])
            score = float(det['score'])
            class_name = str(det.get('class_name', 'hand'))
        cx, cy = center
        in_roi = _point_in_board_roi(cx, cy, board_corners, margin_px)
        out.append(
            HandDetection(
                bbox=bbox,
                center=center,
                score=score,
                class_name=class_name,
                in_board_roi=in_roi,
            )
        )
    return out


class HandPresenceTracker:
    """Debounced hand-in-board tracker."""

    def __init__(self, config: HandPresenceConfig | None = None) -> None:
        self.config = config or HandPresenceConfig()
        self._state = HandPresenceState.ABSENT
        self._present_streak = 0
        self._absent_streak = 0
        self._last_detections: list[HandDetection] = []

    @property
    def state(self) -> HandPresenceState:
        return self._state

    @property
    def hand_in_board(self) -> bool:
        return self._state == HandPresenceState.PRESENT

    def reset(self) -> None:
        self._state = HandPresenceState.ABSENT
        self._present_streak = 0
        self._absent_streak = 0
        self._last_detections = []

    def update(self, detections: list[HandDetection]) -> HandPresenceUpdate:
        self._last_detections = list(detections)
        hand_seen = bool(detections)
        raw_in_board = any(det.in_board_roi for det in detections)
        entered = False
        left = False

        if raw_in_board:
            self._present_streak += 1
            self._absent_streak = 0
            if (
                self._state == HandPresenceState.ABSENT
                and self._present_streak >= self.config.present_frames
            ):
                self._state = HandPresenceState.PRESENT
                entered = True
        else:
            self._absent_streak += 1
            self._present_streak = 0
            if (
                self._state == HandPresenceState.PRESENT
                and self._absent_streak >= self.config.absent_frames
            ):
                self._state = HandPresenceState.ABSENT
                left = True

        return HandPresenceUpdate(
            state=self._state,
            hand_in_board=self.hand_in_board,
            hand_seen=hand_seen,
            hand_present=hand_seen and not raw_in_board,
            entered_board=entered,
            left_board=left,
            detections=detections,
        )
