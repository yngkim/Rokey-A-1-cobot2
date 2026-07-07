"""Tests for FEN-guided depth occupancy sanitization."""

from chess_game.board_utils import occupancy_from_fen, sanitize_depth_cells


def test_sanitize_drops_low_conf_false_positive_on_empty_square() -> None:
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    cells = occupancy_from_fen(fen)
    cells[27] = True  # d4 false positive
    confidence = [0.9 if c else 0.0 for c in cells]
    confidence[27] = 0.15

    sanitized = sanitize_depth_cells(cells, confidence, fen, empty_square_min_conf=0.42)
    assert sanitized[27] is False


def test_sanitize_keeps_high_conf_new_piece_square() -> None:
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    cells = occupancy_from_fen(fen)
    cells[28] = True  # e4 after pawn move
    confidence = [0.9 if c else 0.0 for c in cells]
    confidence[28] = 0.75

    sanitized = sanitize_depth_cells(cells, confidence, fen, empty_square_min_conf=0.42)
    assert sanitized[28] is True
