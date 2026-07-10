"""Map chess square coordinates for physical board orientation."""

from __future__ import annotations


def is_board_flipped(orientation: str) -> bool:
    return orientation.strip().lower() in {'flipped', 'rotated', 'rotated_180', '180'}


def map_square(col: int, row: int, *, flipped: bool) -> tuple[int, int]:
    if flipped:
        return 7 - col, 7 - row
    return col, row
