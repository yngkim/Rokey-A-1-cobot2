"""Bootstrap Doosan DSR_ROBOT2 API (must run before first DSR_ROBOT2 import)."""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import DR_init
import rclpy
from dsr_msgs2.srv import GetCurrentPosx, MoveJoint, MoveLine, MoveStop, MoveWait
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node

DR_COND_NONE = -10000
DR_MV_MOD_ABS = 0
DR_MV_RA_DUPLICATE = 0
DR_BASE = 0
POINT_COUNT = 6
_DEFAULT_SERVICE_TIMEOUT_SEC = 120.0


@dataclass
class DsrApi:
    node: Node
    movej: Callable[..., Any]
    movel: Callable[..., Any]
    mwait: Callable[..., Any]
    get_current_posx: Callable[..., Any]
    move_stop: Callable[..., Any]
    _spin_thread: threading.Thread | None = None


def _wait_future(future, *, timeout_sec: float = _DEFAULT_SERVICE_TIMEOUT_SEC):
    deadline = time.monotonic() + timeout_sec
    while not future.done():
        if time.monotonic() >= deadline:
            raise TimeoutError(f'DSR service call timed out after {timeout_sec}s')
        time.sleep(0.01)
    return future.result()


def _call_service(client, request, *, timeout_sec: float = _DEFAULT_SERVICE_TIMEOUT_SEC) -> Any:
    if not client.wait_for_service(timeout_sec=5.0):
        raise RuntimeError(f'DSR service unavailable: {client.srv_name}')
    future = client.call_async(request)
    return _wait_future(future, timeout_sec=timeout_sec)


def _float64_multi_array_to_list(multi_arr_f64) -> list[list[float]]:
    return [list(item.data) for item in multi_arr_f64]


def _resolve_joint_vel_acc(vel: float | None, acc: float | None) -> tuple[float, float]:
    return float(vel if vel is not None else 0.0), float(acc if acc is not None else 0.0)


def _resolve_task_vel_acc(
    vel: float | list[float] | None,
    acc: float | list[float] | None,
) -> tuple[list[float], list[float]]:
    if isinstance(vel, list):
        resolved_vel = [float(x) for x in vel]
    else:
        resolved_vel = [float(vel if vel is not None else 0.0), float(DR_COND_NONE)]
    if isinstance(acc, list):
        resolved_acc = [float(x) for x in acc]
    else:
        resolved_acc = [float(acc if acc is not None else 0.0), float(DR_COND_NONE)]
    return resolved_vel, resolved_acc


def _make_movej(client) -> Callable[..., int]:
    def movej(pos, vel=None, acc=None, time=None, radius=None, mod=DR_MV_MOD_ABS, ra=DR_MV_RA_DUPLICATE, **_kwargs):
        del time, radius, mod, ra, _kwargs
        joint_vel, joint_acc = _resolve_joint_vel_acc(vel, acc)
        request = MoveJoint.Request()
        request.pos = [float(x) for x in pos]
        request.vel = joint_vel
        request.acc = joint_acc
        request.time = 0.0
        request.mode = DR_MV_MOD_ABS
        request.radius = 0.0
        request.blend_type = DR_MV_RA_DUPLICATE
        request.sync_type = 0
        result = _call_service(client, request)
        return 0 if result and result.success else -1

    return movej


def _make_movel(client) -> Callable[..., int]:
    def movel(pos, vel=None, acc=None, time=None, radius=None, ref=None, mod=DR_MV_MOD_ABS, ra=DR_MV_RA_DUPLICATE, **_kwargs):
        del time, radius, mod, ra, _kwargs
        task_vel, task_acc = _resolve_task_vel_acc(vel, acc)
        request = MoveLine.Request()
        request.pos = [float(x) for x in pos]
        request.vel = task_vel
        request.acc = task_acc
        request.time = 0.0
        request.radius = 0.0
        request.ref = int(DR_BASE if ref is None else ref)
        request.mode = DR_MV_MOD_ABS
        request.blend_type = DR_MV_RA_DUPLICATE
        request.sync_type = 0
        result = _call_service(client, request)
        return 0 if result and result.success else -1

    return movel


def _make_mwait(client) -> Callable[..., int]:
    def mwait(time=0):
        del time
        request = MoveWait.Request()
        result = _call_service(client, request)
        return 0 if result and result.success else -1

    return mwait


def _make_move_stop(client) -> Callable[..., int]:
    def move_stop(stop_mode=0, **_kwargs):
        del _kwargs
        request = MoveStop.Request()
        request.stop_mode = int(stop_mode)
        result = _call_service(client, request, timeout_sec=10.0)
        return 0 if result and result.success else -1

    return move_stop


def _make_get_current_posx(client) -> Callable[..., tuple[list[float] | None, int | None]]:
    def get_current_posx(ref=None):
        request = GetCurrentPosx.Request()
        request.ref = int(DR_BASE if ref is None else ref)
        result = _call_service(client, request)
        if result is None or not result.success:
            return None, None
        posx_info = _float64_multi_array_to_list(result.task_pos_info)
        if not posx_info:
            return None, None
        pos = [float(posx_info[0][index]) for index in range(POINT_COUNT)]
        sol = int(round(posx_info[0][6]))
        return pos, sol

    return get_current_posx


def start_dsr_spin_thread(dsr_api: DsrApi) -> threading.Thread:
    if dsr_api._spin_thread is not None and dsr_api._spin_thread.is_alive():
        return dsr_api._spin_thread

    executor = SingleThreadedExecutor()
    executor.add_node(dsr_api.node)

    def _spin() -> None:
        try:
            executor.spin()
        except Exception:
            pass

    thread = threading.Thread(target=_spin, name='dsr-api-spin', daemon=True)
    thread.start()
    dsr_api._spin_thread = thread
    return thread


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

    movej_client = dsr_node.create_client(MoveJoint, 'motion/move_joint')
    movel_client = dsr_node.create_client(MoveLine, 'motion/move_line')
    mwait_client = dsr_node.create_client(MoveWait, 'motion/move_wait')
    stop_client = dsr_node.create_client(MoveStop, 'motion/move_stop')
    posx_client = dsr_node.create_client(GetCurrentPosx, 'aux_control/get_current_posx')

    api = DsrApi(
        node=dsr_node,
        movej=_make_movej(movej_client),
        movel=_make_movel(movel_client),
        mwait=_make_mwait(mwait_client),
        get_current_posx=_make_get_current_posx(posx_client),
        move_stop=_make_move_stop(stop_client),
    )
    start_dsr_spin_thread(api)
    return api


def read_robot_ids_from_node(node: Node) -> tuple[str, str]:
    robot_id = str(node.get_parameter('robot_id').value).strip() or 'dsr01'
    robot_model = str(node.get_parameter('robot_model').value).strip() or 'm0609'
    return robot_id, robot_model
