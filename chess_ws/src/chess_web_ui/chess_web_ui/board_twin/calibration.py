"""Side-view board calibration: image pixels to chess squares."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class SideViewCalibration:
    board_corners: list[tuple[float, float]]
    flip_files: bool = False
    board_flipped: bool = False
    webcam_device: int = 1
    camera_width: int = 1920
    camera_height: int = 1080

    @classmethod
    def from_json_file(cls, path: str | Path) -> SideViewCalibration:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        raw_corners = payload.get('board_corners') or []
        if len(raw_corners) != 8:
            raise ValueError('board_corners must contain 8 numbers (4 x,y points)')
        corners = [
            (float(raw_corners[i]), float(raw_corners[i + 1]))
            for i in range(0, 8, 2)
        ]
        return cls(
            board_corners=corners,
            flip_files=bool(payload.get('flip_files', False)),
            board_flipped=bool(payload.get('board_flipped', False)),
            webcam_device=int(payload.get('webcam_device', 1)),
            camera_width=int(payload.get('camera_width', 1920)),
            camera_height=int(payload.get('camera_height', 1080)),
        )

    def build_mapper(self) -> SideViewSquareMapper:
        return SideViewSquareMapper(
            corners=self.board_corners,
            flip_files=self.flip_files,
            board_flipped=self.board_flipped,
        )


class SideViewSquareMapper:
  """Perspective map from side-camera pixels to board square names."""

  def __init__(
      self,
      *,
      corners: list[tuple[float, float]],
      flip_files: bool = False,
      board_flipped: bool = False,
  ) -> None:
      if len(corners) != 4:
          raise ValueError('expected 4 board corners')
      self.corners_image = corners
      self.flip_files = flip_files
      self.board_flipped = board_flipped
      src = np.array(corners, dtype=np.float32).reshape(4, 1, 2)
      dst = np.array(
          [[[0, 0]], [[8, 0]], [[8, 8]], [[0, 8]]],
          dtype=np.float32,
      )
      self.image_to_board = cv2.getPerspectiveTransform(src, dst)

  def image_to_square_name(self, x: float, y: float) -> str | None:
      pt = np.array([[[x, y]]], dtype=np.float32)
      board_pt = cv2.perspectiveTransform(pt, self.image_to_board)[0][0]
      col = int(np.clip(np.floor(board_pt[0]), 0, 7))
      row = int(np.clip(np.floor(board_pt[1]), 0, 7))
      if self.board_flipped:
          col, row = 7 - col, 7 - row
      if self.flip_files:
          col = 7 - col
      return f'{chr(ord("a") + col)}{row + 1}'
