"""Physical graveyard side mapping from human chess color."""

from __future__ import annotations


def human_graveyard_side(human_color: str) -> str:
    return human_color.strip().lower()


def robot_graveyard_side(human_color: str) -> str:
    return 'black' if human_color.strip().lower() == 'white' else 'white'


def robot_chess_color(human_color: str) -> str:
    return robot_graveyard_side(human_color)
