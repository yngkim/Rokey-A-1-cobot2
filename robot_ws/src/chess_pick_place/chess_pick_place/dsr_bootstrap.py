"""Bootstrap Doosan DSR_ROBOT2 API (must run before first DSR_ROBOT2 import)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable

import DR_init
import rclpy
from rclpy.node import Node


@dataclass
class DsrApi:
    node: Node
    movej: Callable[..., Any]
    movel: Callable[..., Any]
    mwait: Callable[..., Any]
    get_current_posx: Callable[..., Any]


def bootstrap_dsr(robot_id: str = 'dsr01', robot_model: str = 'm0609') -> DsrApi:
    if not robot_id or not robot_model:
        raise ValueError('robot_id and robot_model must be non-empty')

    if 'DSR_ROBOT2' in sys.modules:
        raise RuntimeError(
            'DSR_ROBOT2 was imported before DR_init setup. '
            'Call bootstrap_dsr() before any other DSR_ROBOT2 import.'
        )

    DR_init.__dsr__id = robot_id
    DR_init.__dsr__model = robot_model

    dsr_node = rclpy.create_node('chess_dsr_api', namespace=robot_id)
    DR_init.__dsr__node = dsr_node

    from DSR_ROBOT2 import get_current_posx, movej, movel, mwait  # noqa: PLC0415

    return DsrApi(
        node=dsr_node,
        movej=movej,
        movel=movel,
        mwait=mwait,
        get_current_posx=get_current_posx,
    )


def read_robot_ids_from_node(node: Node) -> tuple[str, str]:
    robot_id = str(node.get_parameter('robot_id').value).strip() or 'dsr01'
    robot_model = str(node.get_parameter('robot_model').value).strip() or 'm0609'
    return robot_id, robot_model
