"""64-cell board occupancy helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

STARTING_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def starting_occupancy() -> list[bool]:
    """Return occupancy for the standard chess starting position."""
    cells = [False] * 64
    for col in range(8):
        cells[0 * 8 + col] = True
        cells[1 * 8 + col] = True
        cells[6 * 8 + col] = True
        cells[7 * 8 + col] = True
    return cells


@dataclass
class OccupancyGrid:
    cells: list[bool] = field(default_factory=starting_occupancy)
    confidence: list[float] = field(default_factory=lambda: [1.0] * 64)

    def diff_indices(self, other: 'OccupancyGrid') -> list[int]:
        return [idx for idx, (a, b) in enumerate(zip(self.cells, other.cells)) if a != b]
