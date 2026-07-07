"""Tests for promotion_required flow in vision session."""

import chess

from chess_game.board_utils import occupancy_from_fen
from chess_game.game_state import GameState
from chess_web_ui.vision_session import VisionSession

E7_FEN = '8/4P3/8/8/8/8/8/8 w - - 0 1'


def test_promotion_required_without_piece_choice():
    session = VisionSession()
    session.game = GameState(E7_FEN)
    baseline = occupancy_from_fen(E7_FEN)
    session.previous_cells = list(baseline)

    after = list(baseline)
    after[chess.parse_square('e7')] = False
    after[chess.parse_square('e8')] = True

    outcome = session.apply_player_move_scan(after)
    assert not outcome.success
    assert outcome.promotion_required
    assert outcome.message == 'promotion_required'
    assert outcome.from_square == 'e7'
    assert outcome.to_square == 'e8'


def test_apply_player_promotion_completes_move():
    session = VisionSession()
    session.game = GameState(E7_FEN)
    baseline = occupancy_from_fen(E7_FEN)
    session.previous_cells = list(baseline)

    outcome = session.apply_player_promotion('e7', 'e8', 'q')
    assert outcome.success
    assert outcome.uci == 'e7e8q'
    board = chess.Board(outcome.fen)
    assert board.piece_at(chess.parse_square('e8')).symbol().lower() == 'q'
