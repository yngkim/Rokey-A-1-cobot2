"""Capture move detection from occupancy diff."""

from chess_game.board_utils import occupancy_from_fen, square_name_to_index
from chess_game.occupancy_diff import detect_move_from_diff


def _set(cells: list[bool], square: str, occupied: bool) -> None:
    cells[square_name_to_index(square)] = occupied


def test_queen_capture_pawn_one_departed_destination_still_occupied():
    fen = '8/8/3p4/8/8/8/8/3Q4 w - - 0 1'
    before = occupancy_from_fen(fen)
    after = list(before)
    _set(after, 'd1', False)
    assert after[square_name_to_index('d6')]

    diff = detect_move_from_diff(before, after, fen)
    assert diff is not None
    assert diff.from_square == 'd1'
    assert diff.to_square == 'd6'


def test_capture_two_departed_zero_arrived():
    fen = '8/8/3p4/8/8/8/8/3Q4 w - - 0 1'
    before = occupancy_from_fen(fen)
    after = list(before)
    _set(after, 'd1', False)
    _set(after, 'd6', False)

    diff = detect_move_from_diff(before, after, fen)
    assert diff is not None
    assert diff.from_square == 'd1'
    assert diff.to_square == 'd6'
