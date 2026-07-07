"""Unit tests for board restore planning."""

from chess_robot_motion.board_restore_planner import (
    RestoreMove,
    needs_restore,
    plan_restore,
)
from chess_robot_motion.occupancy_grid import STARTING_FEN


def _empty_graveyard() -> list[str | None]:
    return [None] * 16


def test_needs_restore_when_graveyard_occupied():
    slots = _empty_graveyard()
    slots[7] = 'P'
    assert needs_restore(STARTING_FEN, slots)


def test_no_restore_at_start():
    assert not needs_restore(STARTING_FEN, _empty_graveyard())


def test_board_pawn_returns_to_e2():
    fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e3 0 1'
    moves = plan_restore(fen, _empty_graveyard(), robot_graveyard_side='black')
    assert moves == [
        RestoreMove('board_to_graveyard', 'P', 4, 3, 7, 0),
        RestoreMove('graveyard_to_board', 'P', 7, 0, 4, 1),
    ]


def test_graveyard_pawn_to_missing_e2():
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
    slots = _empty_graveyard()
    slots[7] = 'P'
    moves = plan_restore(fen, slots, robot_graveyard_side='black')
    assert any(
        m.kind == 'graveyard_to_board' and m.symbol == 'P' and m.to_col == 4 and m.to_row == 1
        for m in moves
    )


def test_graveyard_lifo_order():
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
    slots = _empty_graveyard()
    slots[7] = 'P'
    slots[6] = 'N'
    fen_missing = 'rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/R1BQKBNR w KQkq - 0 1'
    moves = plan_restore(fen_missing, slots, robot_graveyard_side='black')
    gy_moves = [m for m in moves if m.kind == 'graveyard_to_board']
    assert len(gy_moves) == 2
    assert gy_moves[0].symbol == 'N'
    assert gy_moves[1].symbol == 'P'


def test_graveyard_pawn_when_home_missing():
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
    slots = _empty_graveyard()
    slots[7] = 'P'
    moves = plan_restore(fen, slots, robot_graveyard_side='black')
    assert moves == [
        RestoreMove('graveyard_to_board', 'P', 7, 0, 4, 1),
    ]


def test_starting_fen_with_graveyard_pawn():
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
    slots = _empty_graveyard()
    slots[7] = 'P'
    moves = plan_restore(fen, slots, robot_graveyard_side='black')
    assert moves == [
        RestoreMove('graveyard_to_board', 'P', 7, 0, 4, 1),
    ]


def test_phantom_pawn_after_untracked_user_move_and_capture():
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
    slots = _empty_graveyard()
    slots[7] = 'P'
    moves = plan_restore(fen, slots, robot_graveyard_side='black')
    assert moves == [
        RestoreMove('graveyard_to_board', 'P', 7, 0, 4, 1),
    ]


def test_stale_fen_with_graveyard_requires_sync():
    slots = _empty_graveyard()
    slots[7] = 'P'
    try:
        plan_restore(STARTING_FEN, slots, robot_graveyard_side='black')
    except RuntimeError as exc:
        assert 'out of sync' in str(exc)
    else:
        raise AssertionError('expected out of sync error')


def test_plan_returns_restore_move_type():
    fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e3 0 1'
    moves = plan_restore(fen, _empty_graveyard(), robot_graveyard_side='black')
    assert all(isinstance(m, RestoreMove) for m in moves)


def test_human_graveyard_restore():
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
    robot_slots = _empty_graveyard()
    human_slots = _empty_graveyard()
    human_slots[7] = 'P'
    moves = plan_restore(
        fen,
        robot_slots,
        robot_graveyard_side='black',
        human_slots=human_slots,
        human_graveyard_side='white',
    )
    assert moves == [
        RestoreMove('graveyard_to_board', 'P', 7, 0, 4, 1, graveyard_id='human'),
    ]
