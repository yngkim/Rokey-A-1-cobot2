"""Tests for graveyard side mapping and sync helpers."""

from chess_pick_place.graveyard_sync import (
    apply_human_color_to_graveyards,
    default_human_color_from_robot_param,
    normalize_human_color,
)
from chess_robot_motion.graveyard_pose_map import GraveyardPoseMap
from chess_robot_motion.graveyard_sides import human_graveyard_side, robot_graveyard_side
from chess_robot_motion.graveyard_state import GraveyardState


def test_graveyard_sides_from_human_color():
    assert robot_graveyard_side('white') == 'black'
    assert human_graveyard_side('white') == 'white'
    assert robot_graveyard_side('black') == 'white'
    assert human_graveyard_side('black') == 'black'


def test_default_human_color_from_robot_param():
    assert default_human_color_from_robot_param('black') == 'white'
    assert default_human_color_from_robot_param('white') == 'black'


def test_apply_human_color_to_graveyards_black_human():
    robot_gy = GraveyardState(side='black')
    human_gy = GraveyardState(side='white')
    color = apply_human_color_to_graveyards('black', robot_gy, human_gy)
    assert color == 'black'
    assert robot_gy.side == 'white'
    assert human_gy.side == 'black'


def test_normalize_human_color():
    assert normalize_human_color(' White ') == 'white'
    assert normalize_human_color('invalid') is None


def test_human_black_robot_white_graveyard_negative_col_step():
    robot_gy = GraveyardState(side='black')
    human_gy = GraveyardState(side='white')
    apply_human_color_to_graveyards('black', robot_gy, human_gy)
    assert robot_graveyard_side('black') == 'white'
    assert robot_gy.side == 'white'

    anchor = [596.78, 225.25, 270.85, 26.39, -180.0, 21.9]
    gmap = GraveyardPoseMap(anchor, col_step_mm=-40.0, row_step_mm=40.0, anchor_col=0)
    assert gmap.square_center_xy(0, 0) == (596.78, 225.25)
    assert gmap.square_center_xy(1, 0) == (556.78, 225.25)
    assert gmap.square_center_xy(0, 1) == (596.78, 265.25)
