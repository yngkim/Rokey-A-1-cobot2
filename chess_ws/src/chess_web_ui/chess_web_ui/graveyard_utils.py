"""Graveyard slot helpers (mirrors robot graveyard fill order)."""

from __future__ import annotations

BLACK_GRAVEYARD_FILL_ORDER: list[tuple[int, int]] = [
    (col, 0) for col in range(7, -1, -1)
] + [
    (col, 1) for col in range(7, -1, -1)
]

WHITE_GRAVEYARD_FILL_ORDER: list[tuple[int, int]] = [
    (col, 0) for col in range(8)
] + [
    (col, 1) for col in range(8)
]


def human_graveyard_side(human_color: str) -> str:
    return human_color.strip().lower()


def robot_graveyard_side(human_color: str) -> str:
    return 'black' if human_color.strip().lower() == 'white' else 'white'


def graveyard_fill_order(side: str) -> list[tuple[int, int]]:
    return WHITE_GRAVEYARD_FILL_ORDER if side.strip().lower() == 'white' else BLACK_GRAVEYARD_FILL_ORDER


def graveyard_slot_index(col: int, grave_row: int) -> int:
    return grave_row * 8 + col


def next_empty_graveyard_slot(slots: list[str | None], side: str) -> tuple[int, int] | None:
    for col, grave_row in graveyard_fill_order(side):
        if slots[graveyard_slot_index(col, grave_row)] is None:
            return col, grave_row
    return None


def place_in_graveyard(slots: list[str | None], side: str, symbol: str) -> list[str | None]:
    updated = list(slots)
    slot = next_empty_graveyard_slot(updated, side)
    if slot is None:
        raise ValueError('graveyard is full')
    col, grave_row = slot
    updated[graveyard_slot_index(col, grave_row)] = symbol
    return updated
