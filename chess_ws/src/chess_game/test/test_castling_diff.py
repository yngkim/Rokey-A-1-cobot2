"""Castling detection from occupancy diffs."""

from chess_game.board_utils import occupancy_from_fen, square_name_to_index
from chess_game.occupancy_diff import detect_move_from_diff

# FENs where castling is actually legal (starting position blocks castling paths).
KINGSIDE_FEN = 'rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQK2R w KQkq - 0 1'
QUEENSIDE_FEN = 'r1bqkb1r/pppppppp/8/8/8/8/PPPPPPPP/R3KBNR w Qkq - 0 1'


def _cells_after_move(departed: list[str], arrived: list[str], baseline_fen: str) -> list[bool]:
    cells = occupancy_from_fen(baseline_fen)
    for sq in departed:
        cells[square_name_to_index(sq)] = False
    for sq in arrived:
        cells[square_name_to_index(sq)] = True
    return cells


def test_kingside_castling_four_squares():
    baseline = occupancy_from_fen(KINGSIDE_FEN)
    current = _cells_after_move(['e1', 'h1'], ['f1', 'g1'], KINGSIDE_FEN)
    result = detect_move_from_diff(baseline, current, KINGSIDE_FEN)
    assert result is not None
    assert result.from_square == 'e1'
    assert result.to_square == 'g1'


def test_queenside_castling_four_squares():
    baseline = occupancy_from_fen(QUEENSIDE_FEN)
    current = _cells_after_move(['e1', 'a1'], ['c1', 'd1'], QUEENSIDE_FEN)
    result = detect_move_from_diff(baseline, current, QUEENSIDE_FEN)
    assert result is not None
    assert result.from_square == 'e1'
    assert result.to_square == 'c1'


def test_kingside_castling_king_only():
    baseline = occupancy_from_fen(KINGSIDE_FEN)
    current = _cells_after_move(['e1'], ['g1'], KINGSIDE_FEN)
    result = detect_move_from_diff(baseline, current, KINGSIDE_FEN)
    assert result is not None
    assert result.from_square == 'e1'
    assert result.to_square == 'g1'
