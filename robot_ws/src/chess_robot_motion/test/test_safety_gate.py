"""Tests for SafetyGate pause/resume behavior."""

from __future__ import annotations

import threading
import time

import pytest

from chess_robot_motion.safety_gate import SafetyGate


def test_pause_blocks_until_resume() -> None:
    gate = SafetyGate(poll_sec=0.01)
    gate.request_pause()
    done = threading.Event()

    def worker() -> None:
        gate.wait_if_paused()
        done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    time.sleep(0.05)
    assert not done.is_set()
    gate.resume()
    thread.join(timeout=1.0)
    assert done.is_set()


def test_move_stop_called_on_pause() -> None:
    stops: list[str] = []
    gate = SafetyGate(move_stop=lambda: stops.append('stop'))
    gate.request_pause()
    gate.request_pause()
    assert stops == ['stop']


def test_cancel_raises() -> None:
    gate = SafetyGate(poll_sec=0.01)
    gate.request_pause()
    gate.request_cancel()
    with pytest.raises(RuntimeError, match='canceled'):
        gate.wait_if_paused()


def test_interrupt_flag_set_on_pause_and_consumed_once() -> None:
    gate = SafetyGate(poll_sec=0.01)
    gate.request_pause()
    assert gate.consume_interrupted() is True
    assert gate.consume_interrupted() is False
    gate.resume()
    gate.request_pause()
    assert gate.consume_interrupted() is True


def test_motion_interrupted_consumed_in_planner_move() -> None:
    gate = SafetyGate()
    gate.request_pause()
    assert gate.consume_interrupted() is True
