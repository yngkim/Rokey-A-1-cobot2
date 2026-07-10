"""Sync graveyard state sides from human chess color."""

from __future__ import annotations

from chess_robot_motion.graveyard_sides import human_graveyard_side, robot_graveyard_side
from chess_robot_motion.graveyard_state import GraveyardState


def default_human_color_from_robot_param(robot_color: str) -> str:
    return 'white' if robot_color.strip().lower() == 'black' else 'black'


def normalize_human_color(value: str) -> str | None:
    color = (value or '').strip().lower()
    if color in ('white', 'black'):
        return color
    return None


def apply_human_color_to_graveyards(
    human_color: str,
    robot_graveyard: GraveyardState,
    human_graveyard: GraveyardState,
) -> str:
    color = normalize_human_color(human_color)
    if color is None:
        raise ValueError('human_color must be white or black')
    robot_graveyard.set_side(robot_graveyard_side(color))
    human_graveyard.set_side(human_graveyard_side(color))
    return color
