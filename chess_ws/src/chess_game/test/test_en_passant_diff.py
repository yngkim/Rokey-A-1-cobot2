"""Tests for en passant detection via matcher and diff."""

from __future__ import annotations

from chess_game.board_utils import occupancy_from_fen, square_name_to_index
from chess_game.move_matcher import MoveMatcher
from chess_game.occupancy_diff import detect_move_from_diff, infer_captured_piece

EP_FEN = 'rnbqkbnr/pp2pppp/8/2ppP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3'


def _set(cells: list[bool], square: str, occupied: bool) -> None:
    cells[square_name_to_index(square)] = occupied


def test_en_passant_matcher() -> None:
    before = occupancy_from_fen(EP_FEN)
    after = list(before)
    _set(after, 'e5', False)
    _set(after, 'd5', False)
    _set(after, 'd6', True)

    matcher = MoveMatcher()
    result = matcher.match_from_occupancy(EP_FEN, before, after)
    assert result.matched
    assert result.best == 'e5d6'
    assert infer_captured_piece(EP_FEN, 'e5', 'd6') == 'p'


def test_en_passant_diff() -> None:
    before = occupancy_from_fen(EP_FEN)
    after = list(before)
    _set(after, 'e5', False)
    _set(after, 'd5', False)
    _set(after, 'd6', True)

    diff = detect_move_from_diff(before, after, EP_FEN)
    assert diff is not None
    assert diff.from_square == 'e5'
    assert diff.to_square == 'd6'
