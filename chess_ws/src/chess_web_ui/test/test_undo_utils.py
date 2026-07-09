"""Tests for undo snapshot helpers and reverse-move planning."""

from chess_web_ui.graveyard_utils import place_in_graveyard
from chess_web_ui.undo_utils import (
    build_undo_moves_payload,
    graveyard_pick_from_diff,
    make_ply_snapshot,
    undo_ply_count,
)


START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'


def test_undo_ply_count_human_only():
    snaps = [
        make_ply_snapshot(
            fen=START,
            graveyard_slots=[None] * 16,
            human_graveyard_slots=[None] * 16,
            human_captures=[],
            robot_captures=[],
            move_history=[],
            ply_counter=0,
            uci='e2e4',
            by_robot=False,
        )
    ]
    assert undo_ply_count(snaps) == 1


def test_undo_ply_count_robot_then_human_pair():
    snaps = [
        make_ply_snapshot(
            fen=START,
            graveyard_slots=[None] * 16,
            human_graveyard_slots=[None] * 16,
            human_captures=[],
            robot_captures=[],
            move_history=[],
            ply_counter=0,
            uci='e2e4',
            by_robot=False,
        ),
        make_ply_snapshot(
            fen=AFTER_E4,
            graveyard_slots=[None] * 16,
            human_graveyard_slots=[None] * 16,
            human_captures=[],
            robot_captures=[],
            move_history=[{'uci': 'e2e4'}],
            ply_counter=1,
            uci='e7e5',
            by_robot=True,
        ),
    ]
    assert undo_ply_count(snaps) == 2


def test_graveyard_pick_from_diff_finds_filled_slot():
    before = [None] * 16
    after = place_in_graveyard(before, 'black', 'P')
    pick = graveyard_pick_from_diff(before, after, side='black')
    assert pick is not None
    assert pick['symbol'] == 'P'
    assert pick['side'] == 'black'


def test_build_undo_moves_payload_newest_first():
    empty = [None] * 16
    snaps = [
        make_ply_snapshot(
            fen=START,
            graveyard_slots=empty,
            human_graveyard_slots=empty,
            human_captures=[],
            robot_captures=[],
            move_history=[],
            ply_counter=0,
            uci='e2e4',
            by_robot=False,
        ),
        make_ply_snapshot(
            fen=AFTER_E4,
            graveyard_slots=empty,
            human_graveyard_slots=empty,
            human_captures=[],
            robot_captures=[],
            move_history=[{'uci': 'e2e4'}],
            ply_counter=1,
            uci='e7e5',
            by_robot=True,
        ),
    ]
    target, specs = build_undo_moves_payload(
        snaps,
        current_fen='rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2',
        current_robot_gy=empty,
        current_human_gy=empty,
        robot_side='black',
        human_side='white',
    )
    assert target['uci'] == 'e2e4'
    assert [s['uci'] for s in specs] == ['e7e5', 'e2e4']
