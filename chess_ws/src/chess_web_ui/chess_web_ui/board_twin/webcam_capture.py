"""Persistent side-view webcam capture with device auto-probe."""

from __future__ import annotations

import threading

import cv2
import numpy as np


class PersistentWebcamCapture:
    def __init__(
        self,
        device_id: int,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        *,
        allow_device_fallback: bool = False,
    ) -> None:
        self._preferred_device = device_id
        self._allow_device_fallback = allow_device_fallback
        self._width = width
        self._height = height
        self._fps = fps
        self._capture: cv2.VideoCapture | None = None
        self._active_device: int | None = None
        self._lock = threading.Lock()
        self.last_error = ''
        self.actual_width = 0
        self.actual_height = 0
        self.actual_fps = 0.0

    @property
    def preferred_device(self) -> int:
        return self._preferred_device

    @property
    def active_device(self) -> int | None:
        return self._active_device

    def _candidate_devices(self) -> list[int]:
        if self._allow_device_fallback:
            return [self._preferred_device] + [
                idx for idx in range(16) if idx != self._preferred_device
            ]
        return [self._preferred_device]

    def _configure_capture(self, cap: cv2.VideoCapture) -> None:
        # MJPEG allows higher USB bandwidth for 720p/1080p at 30fps on UVC webcams.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        if self._width > 0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        if self._height > 0:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if self._fps > 0:
            cap.set(cv2.CAP_PROP_FPS, self._fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _open_device(self, device_id: int) -> bool:
        backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
        paths = [f'/dev/video{device_id}', str(device_id)]
        for source in paths:
            for backend in backends:
                try:
                    cap = (
                        cv2.VideoCapture(source, backend)
                        if backend != cv2.CAP_ANY
                        else cv2.VideoCapture(source)
                    )
                except Exception:  # noqa: BLE001
                    continue
                if not cap.isOpened():
                    cap.release()
                    continue
                self._configure_capture(cap)
                # Warm-up reads — many USB webcams return black on first frame.
                for _ in range(5):
                    cap.read()
                self._capture = cap
                self._active_device = device_id
                self.actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                self.actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                self.actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
                self.last_error = ''
                return True
        return False

    def _ensure_open(self) -> bool:
        if self._capture is not None and self._capture.isOpened():
            return True
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        devices = self._candidate_devices()
        for device_id in devices:
            if self._open_device(device_id):
                return True
        tried = ', '.join(str(d) for d in devices)
        self.last_error = (
            f'webcam open failed (preferred /dev/video{self._preferred_device}, tried {tried})'
        )
        return False

    def read(self) -> np.ndarray | None:
        with self._lock:
            if not self._ensure_open():
                return None
            assert self._capture is not None
            ok, frame = self._capture.read()
            if ok and frame is not None and frame.size > 0:
                return frame
            self._capture.release()
            self._capture = None
            if not self._ensure_open():
                return None
            ok, frame = self._capture.read()
            if ok and frame is not None and frame.size > 0:
                return frame
            self.last_error = 'webcam read failed'
            return None

    def release(self) -> None:
        with self._lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None
            self._active_device = None
