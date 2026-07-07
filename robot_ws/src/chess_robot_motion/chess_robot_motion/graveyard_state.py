"""Track captured pieces placed on the graveyard grid."""

from __future__ import annotations

import json
from dataclasses import dataclass

from chess_robot_motion.graveyard_pose_map import graveyard_fill_order, graveyard_slot_name


@dataclass
class GraveyardGrid:
    occupied: list[list[bool]]
    pieces: list[list[str | None]]


class GraveyardState:
    """16-slot graveyard: black h9->a10 or white a0->h-1."""

    SLOT_COUNT = 16

    def __init__(self, side: str = 'black') -> None:
        self.side = side.strip().lower()
        self._fill_order = graveyard_fill_order(self.side)
        self.reset()

    def reset(self) -> None:
        self.slots: list[str | None] = [None] * self.SLOT_COUNT

    @staticmethod
    def slots_from_json(raw: str) -> list[str | None]:
        if not raw.strip():
            return [None] * GraveyardState.SLOT_COUNT
        values = json.loads(raw)
        slots = [value if value else None for value in values]
        if len(slots) < GraveyardState.SLOT_COUNT:
            slots.extend([None] * (GraveyardState.SLOT_COUNT - len(slots)))
        return slots[: GraveyardState.SLOT_COUNT]

    def load_slots(self, slots: list[str | None]) -> None:
        self.reset()
        for idx, symbol in enumerate(slots[: self.SLOT_COUNT]):
            if symbol:
                self.slots[idx] = symbol

    def _index(self, col: int, grave_row: int) -> int:
        return grave_row * 8 + col

    def next_empty_slot(self) -> tuple[int, int] | None:
        for col, grave_row in self._fill_order:
            if self.slots[self._index(col, grave_row)] is None:
                return col, grave_row
        return None

    def place_piece(self, col: int, grave_row: int, symbol: str) -> None:
        idx = self._index(col, grave_row)
        if self.slots[idx] is not None:
            raise ValueError(
                f'graveyard slot {graveyard_slot_name(col, grave_row, self.side)} already occupied'
            )
        self.slots[idx] = symbol

    def is_full(self) -> bool:
        return all(slot is not None for slot in self.slots)

    def piece_at(self, col: int, grave_row: int) -> str | None:
        return self.slots[self._index(col, grave_row)]

    def occupied_slots(self) -> list[tuple[int, int, str]]:
        occupied: list[tuple[int, int, str]] = []
        for col, grave_row in self._fill_order:
            sym = self.slots[self._index(col, grave_row)]
            if sym:
                occupied.append((col, grave_row, sym))
        return occupied

    def occupied_slots_reverse(self) -> list[tuple[int, int, str]]:
        return list(reversed(self.occupied_slots()))

    def empty_slots(self) -> list[tuple[int, int]]:
        return [
            (col, grave_row)
            for col, grave_row in self._fill_order
            if self.slots[self._index(col, grave_row)] is None
        ]

    def remove_piece(self, col: int, grave_row: int) -> str:
        idx = self._index(col, grave_row)
        sym = self.slots[idx]
        if sym is None:
            raise ValueError(
                f'graveyard slot {graveyard_slot_name(col, grave_row, self.side)} is empty'
            )
        self.slots[idx] = None
        return sym

    def to_grid(self) -> GraveyardGrid:
        occupied = [[self.slots[self._index(col, row)] is not None for col in range(8)] for row in range(2)]
        pieces = [[self.slots[self._index(col, row)] for col in range(8)] for row in range(2)]
        return GraveyardGrid(occupied=occupied, pieces=pieces)

    def summary(self) -> str:
        parts: list[str] = []
        for col, grave_row in self._fill_order:
            sym = self.slots[self._index(col, grave_row)]
            if sym:
                parts.append(f'{graveyard_slot_name(col, grave_row, self.side)}={sym}')
        return ', '.join(parts) if parts else 'empty'
