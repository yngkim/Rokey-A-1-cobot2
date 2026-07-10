"""Unit tests for graveyard pose map, state, and FEN piece lookup."""

import os

import yaml

from chess_robot_motion.board_state_manager import BoardStateManager
from chess_robot_motion.graveyard_pose_map import (
    BLACK_GRAVEYARD_FILL_ORDER,
    GRAVEYARD_FILL_ORDER,
    WHITE_GRAVEYARD_FILL_ORDER,
    GraveyardPoseMap,
    graveyard_slot_name,
)
from chess_robot_motion.graveyard_state import GraveyardState


def test_graveyard_fill_order_h9_to_a10():
    names = [graveyard_slot_name(col, row) for col, row in BLACK_GRAVEYARD_FILL_ORDER]
    assert names[:8] == ['h9', 'g9', 'f9', 'e9', 'd9', 'c9', 'b9', 'a9']
    assert names[8:] == ['h10', 'g10', 'f10', 'e10', 'd10', 'c10', 'b10', 'a10']
    assert len(BLACK_GRAVEYARD_FILL_ORDER) == 16
    assert GRAVEYARD_FILL_ORDER == BLACK_GRAVEYARD_FILL_ORDER


def test_white_graveyard_fill_order_a0_to_h_minus1():
    names = [graveyard_slot_name(col, row, side='white') for col, row in WHITE_GRAVEYARD_FILL_ORDER]
    assert names[:8] == ['a0', 'b0', 'c0', 'd0', 'e0', 'f0', 'g0', 'h0']
    assert names[8:] == ['a-1', 'b-1', 'c-1', 'd-1', 'e-1', 'f-1', 'g-1', 'h-1']
    assert len(WHITE_GRAVEYARD_FILL_ORDER) == 16


def test_graveyard_pose_map_offsets_from_h9():
    anchor = [100.0, 200.0, 300.0, 1.0, 2.0, 3.0]
    gmap = GraveyardPoseMap(anchor, col_step_mm=-40.0, row_step_mm=-40.0, anchor_col=7)
    assert gmap.square_center_xy(7, 0) == (100.0, 200.0)
    assert gmap.square_center_xy(6, 0) == (140.0, 200.0)
    assert gmap.square_center_xy(0, 0) == (380.0, 200.0)
    assert gmap.square_center_xy(7, 1) == (100.0, 160.0)
    assert gmap.square_center_xy(0, 1) == (380.0, 160.0)


def test_white_graveyard_pose_map_negative_col_step():
    """Physical white GY: slots advance in -X from a0 anchor."""
    anchor = [100.0, 200.0, 300.0, 1.0, 2.0, 3.0]
    gmap = GraveyardPoseMap(anchor, col_step_mm=-40.0, row_step_mm=40.0, anchor_col=0)
    assert gmap.square_center_xy(0, 0) == (100.0, 200.0)
    assert gmap.square_center_xy(1, 0) == (60.0, 200.0)
    assert gmap.square_center_xy(2, 0) == (20.0, 200.0)


def test_graveyard_state_slot_sequence_black():
    state = GraveyardState(side='black')
    expected = BLACK_GRAVEYARD_FILL_ORDER
    for col, row in expected:
        slot = state.next_empty_slot()
        assert slot == (col, row)
        state.place_piece(col, row, 'P')
    assert state.next_empty_slot() is None
    assert state.is_full()


def test_graveyard_state_slot_sequence_white():
    state = GraveyardState(side='white')
    expected = WHITE_GRAVEYARD_FILL_ORDER
    for col, row in expected:
        slot = state.next_empty_slot()
        assert slot == (col, row)
        state.place_piece(col, row, 'p')
    assert state.next_empty_slot() is None
    assert state.is_full()


def test_vision_manual_overlay_white_graveyard_col_step():
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')
    )
    overlay_path = os.path.join(
        repo_root,
        'robot_ws',
        'src',
        'chess_robot_bringup',
        'config',
        'vision_manual_robot_params.yaml',
    )
    with open(overlay_path, encoding='utf-8') as fh:
        data = yaml.safe_load(fh)
    params = data['pick_place_node']['ros__parameters']
    assert params['white_graveyard_col_step_mm'] == -40.0
    assert params['white_graveyard_row_step_mm'] == 40.0


def test_board_piece_at_from_fen():
    board = BoardStateManager()
    assert board.piece_at(0, 0) == 'R'
    assert board.piece_at(4, 1) == 'P'
    assert board.piece_at(4, 3) is None
    assert board.piece_at(0, 7) == 'r'
