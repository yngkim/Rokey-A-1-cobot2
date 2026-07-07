"""Tests for graveyard reconcile when correcting board FEN."""

from chess_web_ui.graveyard_reconcile import reconcile_graveyards_with_fen
from chess_web_ui.graveyard_utils import place_in_graveyard

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
MISSING_E2 = 'rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1'


def test_reconcile_removes_piece_from_robot_graveyard_when_board_gains_piece():
    robot_slots = place_in_graveyard([None] * 16, 'black', 'P')
    human_slots = [None] * 16
    robot_out, human_out = reconcile_graveyards_with_fen(
        MISSING_E2,
        START,
        robot_slots,
        human_slots,
        robot_side='black',
        human_side='white',
    )
    assert 'P' not in robot_out
    assert human_out == human_slots


def test_reconcile_falls_back_to_human_graveyard():
    robot_slots = [None] * 16
    human_slots = place_in_graveyard([None] * 16, 'white', 'P')
    robot_out, human_out = reconcile_graveyards_with_fen(
        MISSING_E2,
        START,
        robot_slots,
        human_slots,
        robot_side='black',
        human_side='white',
    )
    assert robot_out == robot_slots
    assert 'P' not in human_out
