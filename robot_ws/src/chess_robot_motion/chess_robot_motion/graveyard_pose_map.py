"""Map graveyard squares to robot BASE-frame TCP poses (black h9-a10, white a0-h-1)."""

from __future__ import annotations

from dataclasses import dataclass

# h9 -> g9 -> ... -> a9 -> h10 -> ... -> a10 (same X direction per row)
BLACK_GRAVEYARD_FILL_ORDER: list[tuple[int, int]] = [
    (col, 0) for col in range(7, -1, -1)
] + [
    (col, 1) for col in range(7, -1, -1)
]

# a0 -> b0 -> ... -> h0 -> a-1 -> ... -> h-1 (same X direction per row)
WHITE_GRAVEYARD_FILL_ORDER: list[tuple[int, int]] = [
    (col, 0) for col in range(8)
] + [
    (col, 1) for col in range(8)
]

# Backward-compatible alias
GRAVEYARD_FILL_ORDER = BLACK_GRAVEYARD_FILL_ORDER


@dataclass
class GraveyardCoord:
    col: int
    grave_row: int


def graveyard_fill_order(side: str = 'black') -> list[tuple[int, int]]:
    side = side.strip().lower()
    if side == 'white':
        return WHITE_GRAVEYARD_FILL_ORDER
    return BLACK_GRAVEYARD_FILL_ORDER


def graveyard_slot_name(col: int, grave_row: int, side: str = 'black') -> str:
    side = side.strip().lower()
    if side == 'white':
        rank = 0 if grave_row == 0 else -1
        if rank < 0:
            return f'{chr(ord("a") + col)}{rank}'
        return f'{chr(ord("a") + col)}0'
    return f'{chr(ord("a") + col)}{9 + grave_row}'


class GraveyardPoseMap:
    """8x2 graveyard grid anchored at h9 (black) or a0 (white)."""

    def __init__(
        self,
        anchor_h9_posx: list[float],
        col_step_mm: float = -40.0,
        row_step_mm: float = 40.0,
        anchor_col: int = 7,
        z_pick_mm: float | None = None,
        z_travel_mm: float | None = None,
        z_place_mm: float | None = None,
    ) -> None:
        if len(anchor_h9_posx) < 6:
            raise ValueError('anchor_h9_posx must be [x,y,z,rx,ry,rz]')
        self.anchor_x = float(anchor_h9_posx[0])
        self.anchor_y = float(anchor_h9_posx[1])
        self.anchor_z = float(anchor_h9_posx[2])
        self.fixed_orientation = [float(anchor_h9_posx[3]), float(anchor_h9_posx[4]), float(anchor_h9_posx[5])]
        self.anchor_col = anchor_col
        self.col_step_mm = col_step_mm
        self.row_step_mm = row_step_mm
        self.z_pick_mm = self.anchor_z if z_pick_mm is None else z_pick_mm
        self.z_travel_mm = (self.z_pick_mm + 90.0) if z_travel_mm is None else z_travel_mm
        # Separate "place into slot" depth (defaults to z_pick_mm — used when picking a
        # piece back out of the graveyard, e.g. during restore, must stay unaffected).
        self.z_place_mm = self.z_pick_mm if z_place_mm is None else z_place_mm
        self.travel_extra_mm = 0.0

    @property
    def z_travel_effective_mm(self) -> float:
        """Travel Z over graveyard (board travel + optional extra clearance)."""
        return self.z_travel_mm + self.travel_extra_mm

    def square_center_xy(self, col: int, grave_row: int) -> tuple[float, float]:
        if not (0 <= col <= 7 and 0 <= grave_row <= 1):
            raise ValueError(f'invalid graveyard coord: ({col}, {grave_row})')
        x = self.anchor_x + self.col_step_mm * (col - self.anchor_col)
        y = self.anchor_y + self.row_step_mm * grave_row
        return x, y

    def square_to_posx(self, col: int, grave_row: int, z: float | None = None) -> list[float]:
        x, y = self.square_center_xy(col, grave_row)
        z_val = self.z_pick_mm if z is None else z
        return [x, y, z_val, *self.fixed_orientation]

    def square_to_travel_posx(self, col: int, grave_row: int) -> list[float]:
        return self.square_to_posx(col, grave_row, z=self.z_travel_effective_mm)
