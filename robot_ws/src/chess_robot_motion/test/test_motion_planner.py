"""Tests for ZFirstMotionPlanner safety interrupt handling."""

from __future__ import annotations

import pytest

from chess_robot_motion.motion_planner import MotionInterrupted, ZFirstMotionPlanner
from chess_robot_motion.safety_gate import SafetyGate


class _PoseMap:
    z_pick_mm = 100.0
    z_travel_mm = 200.0
    fixed_orientation = [0.0, 0.0, 0.0]

    def square_center_xy(self, col: int, row: int) -> tuple[float, float]:
        del col, row
        return 10.0, 20.0


def test_motion_interrupted_after_pause_during_move() -> None:
    gate = SafetyGate()

    def movel(*_args, **_kwargs) -> None:
        gate.request_pause()

    planner = ZFirstMotionPlanner(
        _PoseMap(),
        movel=movel,
        mwait=lambda: None,
        get_current_posx=lambda: [[0.0, 0.0, 250.0, 0.0, 0.0, 0.0]],
        safety_gate=gate,
    )
    gate.resume()
    with pytest.raises(MotionInterrupted):
        planner.ensure_travel_height()


class _GraveyardPoseMap(_PoseMap):
    z_place_mm = 97.0


def _recording_planner(moves: list[list[float]]) -> ZFirstMotionPlanner:
    def movel(posx, **_kwargs) -> None:
        moves.append(list(posx))

    return ZFirstMotionPlanner(
        _PoseMap(),
        movel=movel,
        mwait=lambda: None,
        get_current_posx=lambda: [[10.0, 20.0, 250.0, 0.0, 0.0, 0.0]],
    )


def test_descend_to_place_uses_z_pick_when_pose_map_has_no_z_place() -> None:
    """Board squares (no z_place_mm) must keep descending to z_pick_mm, unchanged."""
    moves: list[list[float]] = []
    planner = _recording_planner(moves)
    planner.descend_to_place()
    assert moves[-1][2] == 100.0  # _PoseMap.z_pick_mm


def test_descend_to_place_uses_z_place_when_pose_map_provides_it() -> None:
    """Graveyard pose maps with a lower z_place_mm must place there, not z_pick_mm."""
    moves: list[list[float]] = []
    planner = _recording_planner(moves)
    planner.descend_to_place(pose_map=_GraveyardPoseMap())
    assert moves[-1][2] == 97.0

    moves.clear()
    planner.descend_to_pick(pose_map=_GraveyardPoseMap())
    assert moves[-1][2] == 100.0  # pick-up (e.g. restore) stays at z_pick_mm


def test_move_raises_when_controller_rejects_movel() -> None:
    """dsr_bootstrap's movel() returns -1 when the DSR controller rejects a command
    (e.g. vel/acc over a configured safety limit). This used to be silently
    ignored — the arm stalled but the software carried on as if it had moved,
    desyncing the logical/UI state from physical reality. It must now raise."""
    planner = ZFirstMotionPlanner(
        _PoseMap(),
        movel=lambda *_a, **_kw: -1,
        mwait=lambda: None,
        get_current_posx=lambda: [[10.0, 20.0, 250.0, 0.0, 0.0, 0.0]],
    )
    with pytest.raises(RuntimeError, match='rejected by controller'):
        planner.ensure_travel_height()


def test_move_succeeds_when_movel_returns_zero_or_none() -> None:
    for retval in (0, None):
        planner = ZFirstMotionPlanner(
            _PoseMap(),
            movel=lambda *_a, **_kw: retval,
            mwait=lambda: None,
            get_current_posx=lambda: [[10.0, 20.0, 250.0, 0.0, 0.0, 0.0]],
        )
        planner.ensure_travel_height()  # must not raise


class _LowGraveyardPoseMap(_PoseMap):
    """A graveyard pose map calibrated with a lower travel height than the
    board — the exact situation that must not be crossed at directly."""

    z_travel_mm = 150.0

    def square_center_xy(self, col: int, row: int) -> tuple[float, float]:
        del col, row
        return 500.0, 600.0


def test_move_xy_at_height_uses_destination_xy_but_explicit_z() -> None:
    """Crossing from board to graveyard (or back) must use the destination
    pose map's XY but an explicit, caller-chosen Z — not the destination's own
    (possibly lower/uncleared-for-the-crossing) travel height. Regression for a
    collision: place_piece_at()'s own ensure_travel_height(dest_pose_map)
    switched Z down to the graveyard's height *before* the horizontal flight,
    so the arm crossed back over board pieces at an unsafe height."""
    moves: list[list[float]] = []
    planner = _recording_planner(moves)
    board_safe_z = 200.0  # board's z_travel_mm
    planner.move_xy_at_height(3, 1, _LowGraveyardPoseMap(), board_safe_z)
    assert moves[-1][:2] == [500.0, 600.0]  # graveyard pose map's XY
    assert moves[-1][2] == board_safe_z  # NOT _LowGraveyardPoseMap.z_travel_mm (150.0)
