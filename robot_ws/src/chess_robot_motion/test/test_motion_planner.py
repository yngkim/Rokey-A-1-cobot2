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
