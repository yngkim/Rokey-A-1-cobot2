"""Tests for hand presence ROI and state machine."""

from __future__ import annotations

from dataclasses import dataclass

from chess_web_ui.board_twin.hand_presence import (
    HandDetection,
    HandPresenceConfig,
    HandPresenceState,
    HandPresenceTracker,
    filter_detections_in_board,
)
from chess_web_ui.board_twin.paths import default_hand_model_path, resolve_hand_model_path


@dataclass
class _Det:
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    score: float
    class_name: str = 'hand'


CORNERS = [(0.0, 0.0), (800.0, 0.0), (800.0, 800.0), (0.0, 800.0)]


def test_filter_detections_in_board_roi() -> None:
    inside = _Det((90.0, 90.0, 110.0, 110.0), (100.0, 100.0), 0.9)
    outside = _Det((850.0, 10.0, 870.0, 30.0), (860.0, 20.0), 0.8)
    mapped = filter_detections_in_board([inside, outside], CORNERS, margin_px=0.0)
    assert mapped[0].in_board_roi is True
    assert mapped[1].in_board_roi is False


def test_hand_present_means_outside_board() -> None:
    tracker = HandPresenceTracker()
    inside = HandDetection((0, 0, 10, 10), (100.0, 100.0), 0.9, in_board_roi=True)
    outside = HandDetection((0, 0, 10, 10), (900.0, 20.0), 0.8, in_board_roi=False)

    in_update = tracker.update([inside])
    assert in_update.hand_seen is True
    assert in_update.hand_present is False

    out_update = tracker.update([outside])
    assert out_update.hand_seen is True
    assert out_update.hand_present is True


def test_tracker_enter_and_leave_events() -> None:
    tracker = HandPresenceTracker(HandPresenceConfig(present_frames=2, absent_frames=2))
    det_in = HandDetection((0, 0, 10, 10), (100.0, 100.0), 0.9, in_board_roi=True)

    u1 = tracker.update([det_in])
    assert u1.entered_board is False
    assert tracker.state == HandPresenceState.ABSENT

    u2 = tracker.update([det_in])
    assert u2.entered_board is True
    assert tracker.state == HandPresenceState.PRESENT

    u3 = tracker.update([])
    assert u3.left_board is False
    u4 = tracker.update([])
    assert u4.left_board is True
    assert tracker.state == HandPresenceState.ABSENT


def test_resolve_hand_model_path_prefers_local(tmp_path) -> None:
    custom = tmp_path / 'hand.pt'
    custom.write_bytes(b'fake')
    assert resolve_hand_model_path(str(custom)) == str(custom.resolve())
    try:
        resolved = default_hand_model_path()
        assert 'hand' in resolved.lower() or resolved.endswith('.pt')
    except FileNotFoundError:
        pass
