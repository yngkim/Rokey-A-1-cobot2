"""Tests for physical undo step planning."""

from chess_robot_motion.undo_move import plan_reverse_physical, plan_reverse_uci


def test_plan_reverse_quiet_move():
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    steps = plan_reverse_uci(fen, 'e2e4')
    assert len(steps) == 1
    step = steps[0]
    assert step.kind == 'board_to_board'
    # e4 -> e2
    assert (step.from_col, step.from_row) == (4, 3)
    assert (step.to_col, step.to_row) == (4, 1)


def test_plan_reverse_capture_needs_graveyard_pick():
    fen = 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2'
    pick = {'side': 'black', 'col': 7, 'grave_row': 0, 'symbol': 'p'}
    steps = plan_reverse_uci(fen, 'e4d5', graveyard_pick=pick)
    assert len(steps) == 2
    assert steps[0].kind == 'board_to_board'
    assert steps[1].kind == 'graveyard_to_board'
    assert steps[1].graveyard_side == 'black'
    assert (steps[1].to_col, steps[1].to_row) == (3, 4)


def test_plan_reverse_castling():
    fen = 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1'
    steps = plan_reverse_uci(fen, 'e1g1')
    assert len(steps) == 2
    assert all(s.kind == 'board_to_board' for s in steps)


def test_plan_reverse_physical_quiet():
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    steps = plan_reverse_physical(fen, 'e2', 'e4')
    assert len(steps) == 1
    assert steps[0].kind == 'board_to_board'
    assert (steps[0].from_col, steps[0].from_row) == (4, 3)
    assert (steps[0].to_col, steps[0].to_row) == (4, 1)


def test_plan_reverse_physical_capture_with_graveyard():
    fen = 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2'
    pick = {'side': 'white', 'col': 0, 'grave_row': 0, 'symbol': 'p'}
    steps = plan_reverse_physical(fen, 'e4', 'd5', graveyard_pick=pick)
    assert len(steps) == 2
    assert steps[1].kind == 'graveyard_to_board'
