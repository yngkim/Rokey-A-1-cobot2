"""Thread-safe pause gate for hand-detected robot safety stops."""

from __future__ import annotations

import threading
import time
from typing import Callable


class SafetyGate:
    """Blocks motion between segments while paused (e.g. hand on board)."""

    def __init__(
        self,
        *,
        move_stop: Callable[[], None] | None = None,
        poll_sec: float = 0.05,
    ) -> None:
        self._lock = threading.Lock()
        self._paused = False
        self._cancel_requested = False
        self._was_interrupted = False
        self._move_stop = move_stop
        self._poll_sec = poll_sec

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def request_pause(self) -> None:
        with self._lock:
            if self._paused:
                return
            self._paused = True
            self._was_interrupted = True
        if self._move_stop is not None:
            try:
                self._move_stop()
            except Exception:  # noqa: BLE001
                pass

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def request_cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            self._paused = False

    def clear_cancel(self) -> None:
        with self._lock:
            self._cancel_requested = False

    def wait_if_paused(self) -> None:
        while True:
            with self._lock:
                if self._cancel_requested:
                    raise RuntimeError('safety gate canceled')
                if not self._paused:
                    return
            time.sleep(self._poll_sec)

    def consume_interrupted(self) -> bool:
        with self._lock:
            if not self._was_interrupted:
                return False
            self._was_interrupted = False
            return True

    def check_cancel(self) -> None:
        with self._lock:
            if self._cancel_requested:
                raise RuntimeError('safety gate canceled')
