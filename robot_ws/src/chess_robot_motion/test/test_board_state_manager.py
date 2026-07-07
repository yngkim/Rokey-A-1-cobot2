"""Tests for board_state_manager special moves."""

from __future__ import annotations

import chess

from chess_robot_motion.board_state_manager import BoardStateManager


def test_apply_uci_castling_updates_fen() -> None:
    board = BoardStateManager()
    board.set_fen('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
    for uci in ('e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1c4', 'g8f6'):
        board.apply_uci(uci)
    board.apply_uci('e1g1')
    parsed = chess.Board(board.fen)
    assert parsed.piece_at(chess.G1).piece_type == chess.KING
    assert parsed.piece_at(chess.F1).piece_type == chess.ROOK
    assert parsed.piece_at(chess.E1) is None
    assert parsed.piece_at(chess.H1) is None


EP_FEN = 'rnbqkbnr/pp2pppp/8/2ppP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3'


def test_validate_en_passant() -> None:
    board = BoardStateManager()
    board.set_fen(EP_FEN)
    validation = board.validate_uci('e5d6')
    assert validation.ok
    assert validation.is_en_passant
    assert validation.capture_col == chess.square_file(chess.D5)