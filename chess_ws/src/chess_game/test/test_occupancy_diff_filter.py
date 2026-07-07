"""Tests for occupancy diff legal-move filtering."""

from chess_game.occupancy_diff import detect_move_from_diff


def _starting_cells() -> list[bool]:
    cells = [False] * 64
    for idx in range(16):
        cells[idx] = True
    for idx in range(48, 64):
        cells[idx] = True
    return cells


def test_extra_arrived_false_positive_filtered_by_legal_move() -> None:
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    before = _starting_cells()
    after = list(before)
    after[12] = False  # e2
    after[28] = True   # e4
    after[27] = True   # d4 noise

    result = detect_move_from_diff(before, after, fen)
    assert result is not None
    assert result.confident
    assert result.from_square == 'e2'
    assert result.to_square == 'e4'
