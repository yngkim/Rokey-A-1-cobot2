"""Map chess squares to Doosan BASE-frame TCP poses (mm, deg)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SquareCoord:
    col: int
    row: int


def uci_to_square(uci: str) -> SquareCoord:
    uci = uci.strip().lower()
    if len(uci) != 2:
        raise ValueError(f'Invalid UCI square: {uci!r}')
    col = ord(uci[0]) - ord('a')
    row = int(uci[1]) - 1
    if not (0 <= col <= 7 and 0 <= row <= 7):
        raise ValueError(f'Invalid UCI square: {uci!r}')
    return SquareCoord(col=col, row=row)


def square_to_uci(col: int, row: int) -> str:
    return f'{chr(ord("a") + col)}{row + 1}'


def square_to_index(col: int, row: int) -> int:
    return row * 8 + col


def index_to_square(index: int) -> SquareCoord:
    return SquareCoord(col=index % 8, row=index // 8)


class CalibratedSquarePoseMap:
    """A1-anchored board grid mapped to robot BASE coordinates."""

    def __init__(
        self,
        anchor_a1: tuple[float, float] = (590.274, 135.736),
        square_size_mm: float = 40.0,
        z_pick_mm: float = 291.273,
        z_travel_mm: float = 381.273,
        fixed_orientation: tuple[float, float, float] = (2.805, 179.832, 2.749),
        col_step_mm: float | None = None,
        row_step_mm: float | None = None,
    ) -> None:
        self.anchor_x, self.anchor_y = anchor_a1
        self.square_size_mm = square_size_mm
        self.col_step_mm = -square_size_mm if col_step_mm is None else col_step_mm
        self.row_step_mm = -square_size_mm if row_step_mm is None else row_step_mm
        self.z_pick_mm = z_pick_mm
        self.z_travel_mm = z_travel_mm
        self.fixed_orientation = list(fixed_orientation)

    def square_center_xy(self, col: int, row: int) -> tuple[float, float]:
        x = self.anchor_x + self.col_step_mm * col
        y = self.anchor_y + self.row_step_mm * row
        return x, y

    def a1_pick_posx(self) -> list[float]:
        """Measured TCP at A1 with gripper closed on a piece."""
        return self.square_to_posx(0, 0, z=self.z_pick_mm)

    def square_to_posx(self, col: int, row: int, z: float | None = None) -> list[float]:
        x, y = self.square_center_xy(col, row)
        z_val = self.z_pick_mm if z is None else z
        return [x, y, z_val, *self.fixed_orientation]

    def square_to_travel_posx(self, col: int, row: int) -> list[float]:
        return self.square_to_posx(col, row, z=self.z_travel_mm)

    def uci_to_posx(self, uci: str, z: float | None = None) -> list[float]:
        sq = uci_to_square(uci)
        return self.square_to_posx(sq.col, sq.row, z=z)
