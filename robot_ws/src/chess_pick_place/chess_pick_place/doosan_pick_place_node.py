#!/usr/bin/env python3
"""Doosan M0609 + RG2 chess pick-and-place node (no vision)."""

from __future__ import annotations

import json
import sys
import threading
import time
from enum import Enum

import chess
import rclpy
from chess_msgs.action import ExecuteMove, RestoreBoard
from chess_msgs.msg import BoardOccupancy, BoardState, GameSnapshot
from chess_msgs.srv import ResetBoard, RetreatArm, MoveToObserve, SetBoard, UndoMoves
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import Bool, Header
from std_srvs.srv import Trigger

from chess_robot_motion.board_restore_planner import RestoreMove
from chess_robot_motion.board_state_manager import BoardStateManager
from chess_robot_motion.graveyard_pose_map import GraveyardPoseMap, graveyard_slot_name
from chess_robot_motion.graveyard_state import GraveyardState
from chess_robot_motion.motion_planner import MotionInterrupted, ZFirstMotionPlanner
from chess_robot_motion.safety_gate import SafetyGate
from chess_robot_motion.square_pose_map import CalibratedSquarePoseMap, SquareCoord
from chess_robot_motion.graveyard_sides import robot_chess_color
from chess_robot_motion.undo_move import UndoStep, plan_reverse_physical, plan_reverse_uci
from chess_pick_place.dsr_bootstrap import DsrApi, bootstrap_dsr, read_robot_ids_from_node
from chess_pick_place.graveyard_sync import (
    apply_human_color_to_graveyards,
    default_human_color_from_robot_param,
    normalize_human_color,
)
from chess_pick_place.restore_board import apply_restore_move_to_state, board_needs_restore, plan_board_restore


from robot_control.onrobot import RG


class MotionSegment(str, Enum):
    NONE = ''
    TRAVEL_PICK = 'travel_pick'
    DESCEND_PICK = 'descend_pick'
    ASCEND_PICK = 'ascend_pick'
    TRAVEL_PLACE = 'travel_place'
    DESCEND_PLACE = 'descend_place'
    ASCEND_PLACE = 'ascend_place'
    CAPTURE_TRAVEL = 'capture_travel'
    CAPTURE_DESCEND = 'capture_descend'
    CAPTURE_ASCEND = 'capture_ascend'
    GY_TRAVEL = 'gy_travel'
    GY_DESCEND = 'gy_descend'
    GY_ASCEND = 'gy_ascend'
    RESTORE = 'restore'


# Cap on _ensure_goal_active <-> _replay_motion_segment re-entries per goal (see
# DoosanPickPlaceNode._replay_attempts) — guards against a RecursionError crash when
# the hand signal flickers faster than a segment can complete.
_MAX_REPLAY_ATTEMPTS = 50

# Arm must enter the board ROI during capture/graveyard — ignore hand safety there.
_HAND_IMMUNE_SEGMENTS = frozenset(
    {
        MotionSegment.CAPTURE_TRAVEL,
        MotionSegment.CAPTURE_DESCEND,
        MotionSegment.CAPTURE_ASCEND,
        MotionSegment.GY_TRAVEL,
        MotionSegment.GY_DESCEND,
        MotionSegment.GY_ASCEND,
        MotionSegment.RESTORE,
    }
)


from chess_pick_place.agent_debug_log import agent_log


class DoosanPickPlaceNode(Node):
    def __init__(self, dsr_api: DsrApi) -> None:
        super().__init__('pick_place_node')
        self._declare_parameters()
        self._dsr_node = dsr_api.node
        self._movej = dsr_api.movej
        self._movel = dsr_api.movel
        self._mwait = dsr_api.mwait
        self._get_current_posx = dsr_api.get_current_posx
        self._safety_gate = SafetyGate(move_stop=dsr_api.move_stop)
        self._motion_segment = MotionSegment.NONE
        self._segment_ctx: dict = {}
        self._execute_in_progress = False
        self._at_observe_pose = False
        # _ensure_goal_active <-> _replay_motion_segment can re-enter each other every
        # time a hand-safety interruption clears mid-replay. A rapidly flickering hand
        # signal (many pause/resume cycles per second) can otherwise recurse until
        # Python's recursion limit is hit and the goal crashes with an unhandled
        # RecursionError. This counts replay attempts per goal so we abort cleanly
        # instead once the arm has clearly been stuck fighting the same interruption.
        self._replay_attempts = 0
        self._init_gripper()

        self._human_color_value = default_human_color_from_robot_param(
            str(self.get_parameter('robot_color').value)
        )
        self.board = BoardStateManager()
        self.robot_graveyard = GraveyardState(side='black')
        self.human_graveyard = GraveyardState(side='white')
        self._sync_graveyard_sides()
        self._graveyard_pose_maps: dict[str, GraveyardPoseMap] = {}
        z_pick = float(self.get_parameter('z_pick_mm').value)
        clearance = float(self.get_parameter('z_travel_clearance_mm').value)
        z_travel = float(self.get_parameter('z_travel_mm').value)
        if z_travel <= z_pick:
            z_travel = z_pick + clearance

        self.pose_map = CalibratedSquarePoseMap(
            anchor_a1=tuple(self.get_parameter('anchor_a1').value),
            square_size_mm=float(self.get_parameter('square_size_mm').value),
            z_pick_mm=z_pick,
            z_travel_mm=z_travel,
            fixed_orientation=list(self.get_parameter('fixed_orientation').value),
            board_flipped=self._board_flipped(),
        )
        self.get_logger().info(
            f'A1 pick pose: xy={self.pose_map.anchor_x},{self.pose_map.anchor_y} '
            f'z_pick={self.pose_map.z_pick_mm} z_travel={self.pose_map.z_travel_mm} '
            f'ori={self.pose_map.fixed_orientation}'
        )
        self._init_graveyard_pose_maps_from_params()
        self.motion = ZFirstMotionPlanner(
            self.pose_map,
            movel=self._movel,
            mwait=self._mwait,
            get_current_posx=self._get_current_posx,
            velocity=float(self.get_parameter('velocity').value),
            acceleration=float(self.get_parameter('acceleration').value),
            pick_velocity=float(self.get_parameter('pick_velocity').value),
            pick_acceleration=float(self.get_parameter('pick_acceleration').value),
            place_velocity=float(self.get_parameter('place_velocity').value),
            place_acceleration=float(self.get_parameter('place_acceleration').value),
            retreat_velocity=float(self.get_parameter('retreat_velocity').value),
            retreat_acceleration=float(self.get_parameter('retreat_acceleration').value),
            z_approach_offset_mm=float(self.get_parameter('z_approach_offset_mm').value),
            safety_gate=self._safety_gate,
        )

        self.board_pub = self.create_publisher(BoardState, 'chess/board_state', 10)
        self.snapshot_pub = self.create_publisher(GameSnapshot, 'chess/game_snapshot', 10)

        group = ReentrantCallbackGroup()
        self.create_service(ResetBoard, 'chess/reset_board', self.handle_reset, callback_group=group)
        self.create_service(SetBoard, 'robot/set_board', self.handle_set_board, callback_group=group)
        self.create_service(MoveToObserve, 'robot/move_to_observe', self.handle_observe, callback_group=group)
        self.create_service(RetreatArm, 'robot/retreat_arm', self.handle_retreat, callback_group=group)
        self.create_service(UndoMoves, 'robot/undo_moves', self.handle_undo_moves, callback_group=group)
        self.create_service(Trigger, 'robot/user_stop', self.handle_user_stop, callback_group=group)
        self.create_service(Trigger, 'robot/user_stop_resume', self.handle_user_stop_resume, callback_group=group)
        self.create_service(Trigger, 'robot/user_stop_abort', self.handle_user_stop_abort, callback_group=group)
        self.create_subscription(
            Bool,
            'chess/hand_in_board',
            self._on_hand_in_board,
            10,
            callback_group=group,
        )
        self._action_server = ActionServer(
            self,
            ExecuteMove,
            'robot/execute_move',
            execute_callback=self.execute_move,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=group,
        )
        self._restore_action_server = ActionServer(
            self,
            RestoreBoard,
            'robot/restore_board',
            execute_callback=self.execute_restore_board,
            goal_callback=self.restore_goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=group,
        )

        self._publish_board_state('board initialized')
        self._home_timer = self.create_timer(0.1, self._run_initial_home, callback_group=group)
        self.get_logger().info(
            f'graveyard enabled={self._graveyard_enabled()} '
            f'robot_color={self._robot_color()}'
        )
        self.get_logger().info('Doosan pick-place node ready (services up, homing deferred)')

    def _run_initial_home(self) -> None:
        self._home_timer.cancel()
        try:
            self._go_home()
            self.get_logger().info('Doosan pick-place node at home')
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(
                f'initial home move failed (robot services will still run): {exc}'
            )

    def _should_publish_board_state(self) -> bool:
        return bool(self.get_parameter('publish_board_state').value)

    def _home_vel(self) -> float:
        return float(self.get_parameter('home_velocity').value)

    def _home_acc(self) -> float:
        return float(self.get_parameter('home_acceleration').value)

    def _go_home(self) -> None:
        joints = list(self.get_parameter('home_joints').value)
        self.get_logger().info(f'movej home: {joints}')
        ret = self._movej(joints, vel=self._home_vel(), acc=self._home_acc())
        # movej() returns 0 on success, -1 if the DSR controller rejected the
        # command (e.g. vel/acc over a configured safety limit). Ignoring this used
        # to leave the arm wherever it stalled while the software still marked
        # itself "at observe pose" and let the goal finish as if home succeeded.
        if ret not in (0, None):
            raise RuntimeError(
                f'movej home rejected by controller (ret={ret}) '
                '— check DSR safety velocity/acceleration limits'
            )
        self._mwait()
        self._at_observe_pose = True

    def _set_motion_segment(self, segment: MotionSegment, **ctx) -> None:
        self._motion_segment = segment
        self._segment_ctx = dict(ctx)

    def _run_motion_step(self, goal_handle, fn) -> None:
        while True:
            try:
                fn()
                return
            except MotionInterrupted:
                self._replay_attempts += 1
                if self._replay_attempts > _MAX_REPLAY_ATTEMPTS:
                    goal_handle.abort()
                    agent_log(
                        'doosan_pick_place_node.py:_run_motion_step',
                        'ABORT too many hand interruptions (flickering signal)',
                        {
                            'segment': self._motion_segment.value,
                            'replay_attempts': self._replay_attempts,
                        },
                        hypothesis_id='C',
                    )
                    self.get_logger().error(
                        f'aborting move: {self._replay_attempts} hand interruptions in '
                        f'{self._motion_segment.value} — hand signal may be flickering, '
                        'check camera/lighting'
                    )
                    raise RuntimeError('too many hand interruptions') from None
                self.get_logger().info(
                    f'motion interrupted during {self._motion_segment.value} — recovering '
                    f'(attempt {self._replay_attempts}/{_MAX_REPLAY_ATTEMPTS})'
                )
                self._ensure_goal_active(goal_handle)
                self.motion.ensure_travel_height(self._segment_ctx.get('pose_map'))
                self._replay_motion_segment(goal_handle)

    def _replay_motion_segment(self, goal_handle) -> None:
        seg = self._motion_segment
        ctx = self._segment_ctx
        if seg == MotionSegment.NONE:
            return
        pmap = ctx.get('pose_map')
        col = int(ctx.get('col', 0))
        row = int(ctx.get('row', 0))

        if seg in {
            MotionSegment.TRAVEL_PICK,
            MotionSegment.TRAVEL_PLACE,
            MotionSegment.CAPTURE_TRAVEL,
            MotionSegment.GY_TRAVEL,
        }:
            self._ensure_goal_active(goal_handle)
            self.motion.ensure_travel_height(pmap)
            self._ensure_goal_active(goal_handle)
            self.motion.move_xy_at_travel(col, row, pmap)
            return

        if seg in {
            MotionSegment.DESCEND_PICK,
            MotionSegment.CAPTURE_DESCEND,
        }:
            self._ensure_goal_active(goal_handle)
            self.motion.ensure_travel_height(pmap)
            self._ensure_goal_active(goal_handle)
            self.motion.move_xy_at_travel(col, row, pmap)
            self._ensure_goal_active(goal_handle)
            self.motion.descend_to_pick(pmap)
            self._close_gripper()
            return

        if seg in {
            MotionSegment.DESCEND_PLACE,
            MotionSegment.GY_DESCEND,
        }:
            self._ensure_goal_active(goal_handle)
            self.motion.ensure_travel_height(pmap)
            self._ensure_goal_active(goal_handle)
            self.motion.move_xy_at_travel(col, row, pmap)
            self._ensure_goal_active(goal_handle)
            self.motion.descend_to_place(pmap)
            self._open_gripper()
            return

        if seg in {
            MotionSegment.ASCEND_PICK,
            MotionSegment.CAPTURE_ASCEND,
            MotionSegment.ASCEND_PLACE,
            MotionSegment.GY_ASCEND,
        }:
            self._ensure_goal_active(goal_handle)
            self.motion.ascend_to_travel(
                slow=seg == MotionSegment.ASCEND_PLACE,
                pose_map=pmap,
            )

    def _use_graveyard_for_capture(self, captured_symbol: str | None) -> bool:
        del captured_symbol
        return self._graveyard_enabled()

    def _board_flipped(self) -> bool:
        from chess_robot_motion.board_orientation import is_board_flipped

        return is_board_flipped(str(self.get_parameter('board_orientation').value))

    def _human_color(self) -> str:
        return self._human_color_value

    def _sync_graveyard_sides(self) -> None:
        self._human_color_value = apply_human_color_to_graveyards(
            self._human_color_value,
            self.robot_graveyard,
            self.human_graveyard,
        )

    def _set_human_color(self, human_color: str) -> None:
        color = normalize_human_color(human_color)
        if color is None:
            return
        prev_robot_side = self._robot_graveyard_side()
        self._human_color_value = color
        self._sync_graveyard_sides()
        if self._robot_graveyard_side() != prev_robot_side:
            self._graveyard_pose_maps.clear()
            self._reload_graveyard_pose_maps()

    def _graveyard_enabled(self) -> bool:
        return bool(self.get_parameter('graveyard_enabled').value)

    def _robot_color(self) -> str:
        return robot_chess_color(self._human_color())

    def _is_robot_turn(self) -> bool:
        board = chess.Board(self.board.fen)
        robot_is_white = self._robot_color() == 'white'
        return board.turn == chess.WHITE if robot_is_white else board.turn == chess.BLACK

    def _resolve_captured_symbol(self, captured_symbol: str | None) -> str:
        if captured_symbol:
            return captured_symbol
        default = 'p' if self._robot_color() == 'white' else 'P'
        self.get_logger().warn(
            f'capture piece symbol unknown from local FEN; defaulting to {default} for graveyard'
        )
        return default

    def _robot_graveyard_side(self) -> str:
        from chess_robot_motion.graveyard_sides import robot_graveyard_side

        return robot_graveyard_side(self._human_color())

    def _human_graveyard_side(self) -> str:
        from chess_robot_motion.graveyard_sides import human_graveyard_side

        return human_graveyard_side(self._human_color())

    def _graveyard_use_joint_anchor(self, side: str) -> bool:
        side = side.strip().lower()
        if side == 'white':
            return bool(self.get_parameter('graveyard_a0_anchor_from_joints').value)
        return bool(self.get_parameter('graveyard_h9_anchor_from_joints').value)

    def _graveyard_posx_from_params(self, side: str) -> list[float] | None:
        if self._graveyard_use_joint_anchor(side):
            return None
        side = side.strip().lower()
        key = 'graveyard_a0_posx' if side == 'white' else 'graveyard_h9_posx'
        raw = list(self.get_parameter(key).value)
        if len(raw) < 6:
            return None
        return [float(v) for v in raw[:6]]

    def _graveyard_side_params(self, side: str) -> tuple[str, float, float, int]:
        side = side.strip().lower()
        if side == 'white':
            return (
                'a0',
                float(self.get_parameter('white_graveyard_col_step_mm').value),
                float(self.get_parameter('white_graveyard_row_step_mm').value),
                0,
            )
        return (
            'h9',
            float(self.get_parameter('graveyard_col_step_mm').value),
            float(self.get_parameter('graveyard_row_step_mm').value),
            7,
        )

    def _graveyard_z_levels(self, side: str, anchor_z: float) -> tuple[float, float, float]:
        z_pick_param = self.get_parameter('graveyard_z_pick_mm').value
        z_travel_param = self.get_parameter('graveyard_z_travel_mm').value
        z_pick_mm = float(z_pick_param) if z_pick_param is not None and float(z_pick_param) > 0 else float(anchor_z)
        z_travel_mm = (
            float(z_travel_param)
            if z_travel_param is not None and float(z_travel_param) > 0
            else self.pose_map.z_travel_mm
        )
        pick_offset = float(self.get_parameter('graveyard_z_pick_offset_mm').value)
        if pick_offset == 0.0:
            pick_offset = float(self.get_parameter('graveyard_z_offset_mm').value)
        white_pick_offset = float(self.get_parameter('white_graveyard_z_pick_offset_mm').value)
        if side == 'black':
            z_pick_mm += pick_offset
        elif side == 'white':
            z_pick_mm += white_pick_offset
        # z_place_mm: depth used only when placing a captured piece INTO the graveyard
        # slot. Defaults to z_pick_mm (unchanged) plus a side-specific place offset, so
        # picking a piece back out (restore) is unaffected.
        z_place_mm = z_pick_mm
        if side == 'white':
            z_place_mm += float(self.get_parameter('white_graveyard_z_place_offset_mm').value)
        elif side == 'black':
            z_place_mm += float(self.get_parameter('graveyard_z_place_offset_mm').value)
        return z_pick_mm, z_travel_mm, z_place_mm

    def _build_graveyard_pose_map(self, side: str, anchor_posx: list[float]) -> GraveyardPoseMap:
        anchor_name, col_step, row_step, anchor_col = self._graveyard_side_params(side)
        z_pick_mm, z_travel_mm, z_place_mm = self._graveyard_z_levels(side, anchor_posx[2])
        gy_map = GraveyardPoseMap(
            anchor_h9_posx=anchor_posx,
            col_step_mm=col_step,
            row_step_mm=row_step,
            anchor_col=anchor_col,
            z_pick_mm=z_pick_mm,
            z_travel_mm=z_travel_mm,
            z_place_mm=z_place_mm,
        )
        gy_map.travel_extra_mm = float(self.get_parameter('graveyard_z_travel_extra_mm').value)
        self.get_logger().info(
            f'graveyard {anchor_name} from params: xy={gy_map.anchor_x},'
            f'{gy_map.anchor_y} z_pick={gy_map.z_pick_mm} z_place={gy_map.z_place_mm} '
            f'z_travel={gy_map.z_travel_mm} travel_extra={gy_map.travel_extra_mm}'
        )
        return gy_map

    def _init_graveyard_pose_maps_from_params(self) -> None:
        if not self._graveyard_enabled():
            return
        for side in ('black', 'white'):
            posx = self._graveyard_posx_from_params(side)
            if posx is None:
                continue
            self._graveyard_pose_maps[side] = self._build_graveyard_pose_map(side, posx)

    def _reload_graveyard_pose_maps(self) -> None:
        self._graveyard_pose_maps.clear()
        self._init_graveyard_pose_maps_from_params()

    def _graveyard_pose_map_for(self, side: str) -> GraveyardPoseMap:
        if side not in self._graveyard_pose_maps:
            posx = self._graveyard_posx_from_params(side)
            if posx is None:
                raise RuntimeError(
                    f'graveyard {side} posx missing in params — no physical calibration'
                )
            self._graveyard_pose_maps[side] = self._build_graveyard_pose_map(side, posx)
        return self._graveyard_pose_maps[side]

    def _place_captured_in_graveyard(self, captured_symbol: str, goal_handle) -> None:
        # A captured piece is always the *opposite* color of whoever captured it,
        # so the captured piece's own color tells us which graveyard it belongs
        # in: if it's the robot's own color, the human captured it (including via
        # a voice-commanded move the arm executes on their behalf), so it goes in
        # the human's graveyard, not the robot's. This used to always use the
        # robot's own side/state unconditionally, which — for any human capture —
        # sent the piece toward the wrong (possibly full/differently-calibrated)
        # graveyard and left it desynced from web_bridge's own graveyard tracking
        # (which correctly attributes it to the human).
        captured_is_robot_color = captured_symbol.isupper() == (self._robot_color() == 'white')
        if captured_is_robot_color:
            side = self._human_graveyard_side()
            graveyard = self.human_graveyard
        else:
            side = self._robot_graveyard_side()
            graveyard = self.robot_graveyard
        pose_map = self._graveyard_pose_map_for(side)
        if graveyard.is_full():
            raise RuntimeError('graveyard full (16 slots occupied)')
        slot = graveyard.next_empty_slot()
        if slot is None:
            raise RuntimeError('graveyard full (no empty slot)')
        grave_col, grave_row = slot
        slot_name = graveyard_slot_name(grave_col, grave_row, side=side)
        target_x, target_y = pose_map.square_center_xy(grave_col, grave_row)
        self.get_logger().info(
            f'graveyard place {slot_name} side={side} ({captured_symbol}) '
            f'xy=({target_x:.3f},{target_y:.3f}) z_place={pose_map.z_place_mm:.3f}'
        )

        self._set_motion_segment(
            MotionSegment.GY_TRAVEL,
            col=grave_col,
            row=grave_row,
            pose_map=pose_map,
        )
        self._ensure_goal_active(goal_handle)

        def _gy_travel() -> None:
            # Cross to the graveyard slot's XY at the board's travel height
            # (calibrated to clear every board square) — arm is currently
            # positioned directly over the just-captured board square, and the
            # naive "ensure_travel_height(graveyard_pose_map) then move" order
            # switches Z down to the graveyard's own (potentially lower)
            # calibration BEFORE flying back over the rest of the board,
            # risking a collision with pieces still on it. Only switch to the
            # graveyard's travel height once already positioned over the
            # graveyard.
            self.motion.move_xy_at_height(grave_col, grave_row, pose_map, self.pose_map.z_travel_mm)
            self.motion.ensure_travel_height(pose_map)

        self._run_motion_step(goal_handle, _gy_travel)

        self._set_motion_segment(
            MotionSegment.GY_DESCEND,
            col=grave_col,
            row=grave_row,
            pose_map=pose_map,
        )
        self._ensure_goal_active(goal_handle)

        def _gy_place() -> None:
            self.motion.descend_to_place(pose_map)
            self._open_gripper()

        self._run_motion_step(goal_handle, _gy_place)

        self._set_motion_segment(
            MotionSegment.GY_ASCEND,
            col=grave_col,
            row=grave_row,
            pose_map=pose_map,
        )
        self._ensure_goal_active(goal_handle)
        self._run_motion_step(
            goal_handle,
            lambda: self.motion.ascend_to_travel(slow=False, pose_map=pose_map),
        )

        graveyard.place_piece(grave_col, grave_row, captured_symbol)
        self.get_logger().info(f'graveyard state: {graveyard.summary()}')

    def _declare_parameters(self) -> None:
        self.declare_parameter('anchor_a1', [590.274, 135.736])
        self.declare_parameter('square_size_mm', 40.0)
        self.declare_parameter('z_pick_mm', 291.273)
        self.declare_parameter('z_travel_clearance_mm', 90.0)
        self.declare_parameter('z_travel_mm', 381.273)
        self.declare_parameter('fixed_orientation', [2.805, 179.832, 2.749])
        self.declare_parameter('gripper_open_width', 315)
        self.declare_parameter('gripper_close_width', 0)
        self.declare_parameter('gripper_force', 100)
        self.declare_parameter('gripper_name', 'rg2')
        self.declare_parameter('gripper_ip', '192.168.1.1')
        self.declare_parameter('gripper_port', '502')
        self.declare_parameter('velocity', 120.0)
        self.declare_parameter('acceleration', 120.0)
        self.declare_parameter('pick_velocity', 80.0)
        self.declare_parameter('pick_acceleration', 80.0)
        self.declare_parameter('place_velocity', 35.0)
        self.declare_parameter('place_acceleration', 35.0)
        self.declare_parameter('retreat_velocity', 60.0)
        self.declare_parameter('retreat_acceleration', 60.0)
        self.declare_parameter('home_velocity', 50.0)
        self.declare_parameter('home_acceleration', 50.0)
        self.declare_parameter('z_approach_offset_mm', 25.0)
        self.declare_parameter('robot_id', 'dsr01')
        self.declare_parameter('robot_model', 'm0609')
        self.declare_parameter('home_joints', [-12.32, 22.41, 36.08, -0.09, 121.46, -13.86])
        self.declare_parameter('publish_board_state', True)
        self.declare_parameter('robot_color', 'black')
        self.declare_parameter('board_orientation', 'standard')
        self.declare_parameter('graveyard_enabled', True)
        self.declare_parameter('graveyard_h9_joints', [-37.12, 8.08, 106.52, -0.02, 65.41, -36.25])
        # [x, y, z, rx, ry, rz] BASE TCP at h9 anchor; empty = joint-teach fallback only
        self.declare_parameter('graveyard_h9_posx', [310.274, -124.264, 266.273, 2.805, 179.832, 2.749])
        self.declare_parameter('graveyard_square_mm', 40.0)
        self.declare_parameter('graveyard_col_step_mm', -40.0)
        self.declare_parameter('graveyard_row_step_mm', -40.0)
        self.declare_parameter('graveyard_z_pick_mm', 0.0)
        self.declare_parameter('graveyard_z_travel_mm', 0.0)
        self.declare_parameter('graveyard_z_offset_mm', 0.0)  # deprecated: use graveyard_z_pick_offset_mm
        self.declare_parameter('graveyard_z_pick_offset_mm', 0.0)
        # Extra depth applied only when placing a piece INTO the graveyard (not when
        # picking it back out during restore). Negative = lower.
        self.declare_parameter('graveyard_z_place_offset_mm', 0.0)
        self.declare_parameter('graveyard_z_travel_extra_mm', 0.0)
        self.declare_parameter('graveyard_a0_joints', [20.12, 41.84, 55.64, -0.03, 82.52, 15.62])
        # Used only when graveyard_a0_anchor_from_joints is false (see joint teach at startup).
        self.declare_parameter(
            'graveyard_a0_posx', [596.78, 225.25, 270.85, 26.39, -180.0, 21.9]
        )
        self.declare_parameter('graveyard_a0_anchor_from_joints', False)
        self.declare_parameter('graveyard_teach_velocity', 25.0)
        self.declare_parameter('graveyard_h9_anchor_from_joints', False)
        self.declare_parameter('white_graveyard_col_step_mm', -40.0)
        self.declare_parameter('white_graveyard_row_step_mm', 40.0)
        self.declare_parameter('white_graveyard_z_pick_offset_mm', 0.0)
        # Extra depth applied only when placing a piece INTO the white graveyard
        # (a0-h0, a-1/h-1) — not when picking it back out during restore.
        # Negative = lower. Default 0 — a -3.0 test caused the arm to stall mid
        # gy_descend (likely pressing into the tray surface); tune in small
        # (~-1mm) steps with careful physical observation if this is revisited.
        self.declare_parameter('white_graveyard_z_place_offset_mm', 0.0)

    def _init_gripper(self) -> None:
        self.gripper = RG(
            self.get_parameter('gripper_name').value,
            self.get_parameter('gripper_ip').value,
            self.get_parameter('gripper_port').value,
        )
        self.get_logger().info('Gripper ready (opens on first move)')

    def _gripper_force(self) -> int:
        return int(self.get_parameter('gripper_force').value)

    def _wait_gripper(self) -> None:
        while self.gripper.get_status()[0]:
            time.sleep(0.1)

    def _open_gripper(self) -> None:
        width = int(self.get_parameter('gripper_open_width').value)
        self.gripper.move_gripper(width, self._gripper_force())
        self._wait_gripper()

    def _close_gripper(self) -> None:
        width = int(self.get_parameter('gripper_close_width').value)
        self.gripper.move_gripper(width, self._gripper_force())
        self._wait_gripper()

    def goal_callback(self, goal_request):
        if self._execute_in_progress:
            self.get_logger().warn('rejecting execute_move — previous goal still running')
            return GoalResponse.REJECT
        move = goal_request.move
        from_col = int(move.from_square.col)
        from_row = int(move.from_square.row)
        from_name = f'{chr(ord("a") + from_col)}{from_row + 1}'
        to_col = int(move.to_square.col)
        to_row = int(move.to_square.row)
        to_name = f'{chr(ord("a") + to_col)}{to_row + 1}'
        raw_uci = f'{from_name}{to_name}{move.promotion or ""}'

        validation = self.board.validate_uci(raw_uci)
        if not validation.ok:
            self.get_logger().warn(f'execute_move goal rejected: {validation.message}')
            return GoalResponse.REJECT
        from_piece = self.board.piece_at(from_col, from_row)
        # validate_uci() already requires the move be in board.legal_moves for the
        # side whose turn it currently is per this node's own FEN — that alone
        # guarantees from_piece belongs to the side to move, no separate re-check
        # needed. This used to also require the piece be the robot's own color
        # (_is_robot_turn/_piece_symbol_is_robot), which made sense back when the
        # arm only ever played its own moves — but voice commands now have the
        # arm execute the *human's* moves on their behalf too, on the human's own
        # turn, so that restriction rejected every voice move with "goal rejected".
        # #region agent log
        agent_log(
            'doosan_pick_place_node.py:goal_callback',
            'ACCEPT execute_move goal',
            {
                'uci': raw_uci,
                'from_piece': from_piece,
                'fen': self.board.fen,
                'human_color': self._human_color(),
                'robot_color': self._robot_color(),
                'is_robot_turn': self._is_robot_turn(),
            },
            hypothesis_id='B',
        )
        # #endregion
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        del goal_handle
        return CancelResponse.ACCEPT

    def restore_goal_callback(self, goal_request):
        # RestoreBoard.Goal has no fields — it must not reuse execute_move's
        # goal_callback, which unconditionally reads goal_request.move (an
        # ExecuteMove-only field). Doing so raised an uncaught AttributeError
        # here on every restore attempt, so the client never got an accept/
        # reject response and just timed out ("failed to send restore goal").
        del goal_request
        if self._execute_in_progress:
            self.get_logger().warn('rejecting restore_board — a move is already executing')
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _on_hand_in_board(self, msg: Bool) -> None:
        segment = self._motion_segment
        hand_immune = segment in _HAND_IMMUNE_SEGMENTS
        # #region agent log
        agent_log(
            'doosan_pick_place_node.py:_on_hand_in_board',
            'hand topic',
            {
                'in_board': bool(msg.data),
                'safety_paused': self._safety_gate.paused,
                'fen': self.board.fen,
                'is_robot_turn': self._is_robot_turn(),
                'segment': segment.value,
                'hand_immune': hand_immune,
            },
            hypothesis_id='C',
        )
        # #endregion
        if msg.data:
            if hand_immune:
                # #region agent log
                agent_log(
                    'doosan_pick_place_node.py:_on_hand_in_board',
                    'hand pause ignored (capture/graveyard segment)',
                    {'segment': segment.value},
                    hypothesis_id='F',
                )
                # #endregion
                return
            if self._safety_gate.paused:
                return
            self._safety_gate.request_pause()
            self.get_logger().info('hand detected on board — motion paused')
        else:
            if not self._safety_gate.paused:
                return
            self._safety_gate.resume()
            self.get_logger().info('hand cleared — motion resumed')

    def _ensure_goal_active(self, goal_handle) -> None:
        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
            raise RuntimeError('canceled')
        # goal_callback() already validated this move against self.board at accept
        # time, and self.board's turn only flips once the move is applied at the
        # end of execution — so it can't legitimately change mid-flight for the
        # goal that's currently running. This used to also assert _is_robot_turn()
        # here, which aborted every voice-assisted human move (they execute while
        # self.board still shows the human's turn, by definition, for their whole
        # physical execution) — see the same fix in goal_callback().
        self._safety_gate.wait_if_paused()
        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
            raise RuntimeError('canceled')
        if self._safety_gate.consume_interrupted():
            self._replay_attempts += 1
            if self._replay_attempts > _MAX_REPLAY_ATTEMPTS:
                goal_handle.abort()
                # #region agent log
                agent_log(
                    'doosan_pick_place_node.py:_ensure_goal_active',
                    'ABORT too many hand interruptions (flickering signal)',
                    {
                        'segment': self._motion_segment.value,
                        'replay_attempts': self._replay_attempts,
                    },
                    hypothesis_id='C',
                )
                # #endregion
                self.get_logger().error(
                    f'aborting move: {self._replay_attempts} hand interruptions in '
                    f'{self._motion_segment.value} — hand signal may be flickering, '
                    'check camera/lighting'
                )
                raise RuntimeError('too many hand interruptions')
            self.get_logger().info(
                f'hand pause cleared — replaying segment {self._motion_segment.value} '
                f'(attempt {self._replay_attempts}/{_MAX_REPLAY_ATTEMPTS})'
            )
            self.motion.ensure_travel_height(self._segment_ctx.get('pose_map'))
            self._replay_motion_segment(goal_handle)

    def handle_reset(self, request, response):
        del request
        self._execute_in_progress = False
        self._motion_segment = MotionSegment.NONE
        self._segment_ctx = {}
        self._safety_gate.stop_motion()
        self._safety_gate.request_cancel()
        self._safety_gate.clear_cancel()
        self._safety_gate.resume()
        self.board.reset()
        self.robot_graveyard.reset()
        self.human_graveyard.reset()

        home_error: str | None = None

        def _physical_reset() -> None:
            nonlocal home_error
            try:
                self._open_gripper()
                self._go_home()
            except Exception as exc:  # noqa: BLE001
                home_error = str(exc)
                self.get_logger().warn(f'reset homing failed: {exc}')

        worker = threading.Thread(target=_physical_reset, daemon=True, name='reset_home')
        worker.start()
        worker.join(timeout=12.0)
        if worker.is_alive():
            home_error = home_error or 'go_home timed out (12s)'
            self.get_logger().warn(
                'reset go_home timed out — logical board reset still applied'
            )

        self._publish_board_state('board reset to starting position')
        response.success = True
        # Logical board reset always succeeds independently of the physical arm, but a
        # homing failure/timeout used to be swallowed into a ROS log line only — the UI
        # showed a plain "board reset" success with no hint the arm never moved. Surface
        # it in the response message instead.
        response.message = (
            'board reset'
            if home_error is None
            else f'board reset (로봇 홈 복귀 실패: {home_error})'
        )
        return response

    def handle_set_board(self, request, response):
        fen = request.fen.strip()
        if not fen:
            response.success = False
            response.message = 'empty FEN'
            return response
        try:
            self.board.set_fen(fen)
            graveyard_json = getattr(request, 'graveyard_slots_json', '') or ''
            if graveyard_json.strip():
                self.robot_graveyard.load_slots(GraveyardState.slots_from_json(graveyard_json))
            human_gy_json = getattr(request, 'human_graveyard_slots_json', '') or ''
            if human_gy_json.strip():
                self.human_graveyard.load_slots(GraveyardState.slots_from_json(human_gy_json))
            human_color = getattr(request, 'human_color', '') or ''
            if human_color.strip():
                self._set_human_color(human_color)
            orientation = getattr(request, 'board_orientation', '') or ''
            if orientation.strip():
                self.set_parameters([
                    Parameter(
                        'board_orientation',
                        Parameter.Type.STRING,
                        orientation.strip().lower(),
                    )
                ])
                self.pose_map.board_flipped = self._board_flipped()
            response.success = True
            response.message = 'robot board synced from FEN'
            response.fen = self.board.fen
        except Exception as exc:  # noqa: BLE001
            response.success = False
            response.message = str(exc)
        return response

    def _graveyard_for_side(self, side: str) -> GraveyardState:
        side = side.strip().lower()
        if side == self._robot_graveyard_side():
            return self.robot_graveyard
        if side == self._human_graveyard_side():
            return self.human_graveyard
        raise RuntimeError(f'unknown graveyard side {side!r}')

    def _execute_undo_step(self, step: UndoStep) -> None:
        self._open_gripper()
        if step.kind == 'board_to_board':
            self.motion.pick_piece_at(step.from_col, step.from_row, self._close_gripper)
            self.motion.place_piece_at(step.to_col, step.to_row, self._open_gripper)
            symbol = self.board.remove_piece_at(step.from_col, step.from_row)
            if symbol is not None:
                self.board.put_piece_at(step.to_col, step.to_row, symbol)
            return

        if step.kind == 'graveyard_to_board':
            if not step.graveyard_side:
                raise RuntimeError('graveyard_to_board step missing graveyard_side')
            gy = self._graveyard_for_side(step.graveyard_side)
            pose_map = self._graveyard_pose_map_for(step.graveyard_side)
            self.motion.pick_piece_at(
                step.from_col,
                step.from_row,
                self._close_gripper,
                pose_map=pose_map,
            )
            self.motion.ensure_travel_height(self.pose_map)
            self.motion.place_piece_at(
                step.to_col,
                step.to_row,
                self._open_gripper,
                pose_map=self.pose_map,
            )
            symbol = gy.remove_piece(step.from_col, step.from_row)
            self.board.put_piece_at(step.to_col, step.to_row, symbol)
            return

        raise ValueError(f'unknown undo step kind: {step.kind}')

    def handle_undo_moves(self, request, response):
        try:
            moves = json.loads(request.moves_json or '[]')
            if not isinstance(moves, list) or not moves:
                response.success = False
                response.message = 'empty undo moves_json'
                return response

            for entry in moves:
                fen_before = str(entry.get('fen_before', '')).strip()
                pick = entry.get('graveyard_pick')
                if pick is not None and pick.get('side'):
                    self._graveyard_pose_map_for(str(pick['side']))
                mode = str(entry.get('mode', 'uci')).strip().lower()
                if mode == 'physical':
                    from_sq = str(entry.get('from_square', '')).strip()
                    to_sq = str(entry.get('to_square', '')).strip()
                    steps = plan_reverse_physical(
                        fen_before,
                        from_sq,
                        to_sq,
                        graveyard_pick=pick,
                    )
                    label = f'physical {from_sq}->{to_sq}'
                else:
                    uci = str(entry.get('uci', '')).strip()
                    steps = plan_reverse_uci(fen_before, uci, graveyard_pick=pick)
                    label = uci
                self.get_logger().info(f'undo {label}: {len(steps)} steps')
                for step in steps:
                    self._execute_undo_step(step)

            oldest = moves[-1]
            self.board.set_fen(str(oldest.get('fen_before', '')).strip())
            self._go_home()
            self._publish_board_state('undo moves completed')
            response.success = True
            response.message = f'undid {len(moves)} move(s)'
            return response
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'undo moves failed: {exc}')
            response.success = False
            response.message = str(exc)
            return response

    def handle_observe(self, request, response):
        del request
        if self._at_observe_pose:
            self.get_logger().info('move_to_observe: already at observe/home — skipping movej')
        else:
            self.get_logger().info('move_to_observe: moving to home/observe joints')
            self._go_home()
        response.success = True
        response.message = 'at observe pose (home joints)'
        return response

    def handle_retreat(self, request, response):
        del request
        self._go_home()
        self._open_gripper()
        response.success = True
        response.message = 'retreated to home joints'
        return response

    def handle_user_stop(self, request, response):
        del request
        self._safety_gate.request_pause()
        self.get_logger().info('user stop — motion halted')
        response.success = True
        response.message = 'stopped'
        return response

    def handle_user_stop_resume(self, request, response):
        del request
        self._safety_gate.resume()
        self.get_logger().info('user stop resume — motion gate open')
        response.success = True
        response.message = 'resumed'
        return response

    def handle_user_stop_abort(self, request, response):
        del request
        self._execute_in_progress = False
        self._motion_segment = MotionSegment.NONE
        self._segment_ctx = {}
        self._safety_gate.stop_motion()
        self._safety_gate.request_cancel()
        try:
            self._open_gripper()
            self._go_home()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'user stop abort homing failed: {exc}')
        self._safety_gate.clear_cancel()
        self._safety_gate.resume()
        self.get_logger().info('user stop abort — canceled and homed')
        response.success = True
        response.message = 'aborted'
        return response

    def _capture_square_to_graveyard(
        self,
        col: int,
        row: int,
        goal_handle,
        feedback: ExecuteMove.Feedback,
        *,
        progress_start: int,
        progress_end: int,
    ) -> None:
        captured_symbol = self.board.piece_at(col, row)
        if not self._use_graveyard_for_capture(captured_symbol):
            raise RuntimeError('graveyard disabled; cannot capture piece')
        captured_symbol = self._resolve_captured_symbol(captured_symbol)
        # #region agent log
        agent_log(
            'doosan_pick_place_node.py:_capture_square_to_graveyard',
            'capture to graveyard start',
            {
                'col': col,
                'row': row,
                'symbol': captured_symbol,
                'fen': self.board.fen,
            },
            hypothesis_id='F',
        )
        # #endregion

        feedback.progress = progress_start
        feedback.status = 'removing captured piece'
        goal_handle.publish_feedback(feedback)

        self._open_gripper()

        self._set_motion_segment(MotionSegment.CAPTURE_TRAVEL, col=col, row=row)
        self._ensure_goal_active(goal_handle)
        self._run_motion_step(goal_handle, lambda: self.motion.ensure_travel_height())

        self._set_motion_segment(MotionSegment.CAPTURE_DESCEND, col=col, row=row)
        self._ensure_goal_active(goal_handle)

        def _capture_pick() -> None:
            self.motion.move_xy_at_travel(col, row)
            self.motion.descend_to_pick()
            self._close_gripper()

        self._run_motion_step(goal_handle, _capture_pick)

        self._set_motion_segment(MotionSegment.CAPTURE_ASCEND, col=col, row=row)
        self._ensure_goal_active(goal_handle)
        self._run_motion_step(goal_handle, lambda: self.motion.ascend_to_travel())

        feedback.progress = progress_end
        feedback.status = 'placing captured piece in graveyard'
        goal_handle.publish_feedback(feedback)

        self._place_captured_in_graveyard(captured_symbol, goal_handle)
        self.motion.ensure_travel_height()

    def _pick_and_place(
        self,
        from_col: int,
        from_row: int,
        to_col: int,
        to_row: int,
        goal_handle,
        feedback: ExecuteMove.Feedback,
        *,
        progress_pick: int,
        progress_place: int,
    ) -> None:
        self._open_gripper()
        feedback.progress = progress_pick
        feedback.status = 'travel to pick square'
        goal_handle.publish_feedback(feedback)

        self._set_motion_segment(MotionSegment.TRAVEL_PICK, col=from_col, row=from_row)
        self._ensure_goal_active(goal_handle)

        def _travel_pick() -> None:
            self.motion.ensure_travel_height()
            self.motion.move_xy_at_travel(from_col, from_row)

        self._run_motion_step(goal_handle, _travel_pick)

        feedback.status = 'picking'
        goal_handle.publish_feedback(feedback)

        self._set_motion_segment(MotionSegment.DESCEND_PICK, col=from_col, row=from_row)
        self._ensure_goal_active(goal_handle)

        def _descend_pick() -> None:
            self.motion.descend_to_pick()
            self._close_gripper()

        self._run_motion_step(goal_handle, _descend_pick)

        self._set_motion_segment(MotionSegment.ASCEND_PICK, col=from_col, row=from_row)
        self._ensure_goal_active(goal_handle)
        self._run_motion_step(goal_handle, lambda: self.motion.ascend_to_travel())

        feedback.progress = progress_place
        feedback.status = 'travel to place square'
        goal_handle.publish_feedback(feedback)

        self._set_motion_segment(MotionSegment.TRAVEL_PLACE, col=to_col, row=to_row)
        self._ensure_goal_active(goal_handle)
        self._run_motion_step(goal_handle, lambda: self.motion.move_xy_at_travel(to_col, to_row))

        self._set_motion_segment(MotionSegment.DESCEND_PLACE, col=to_col, row=to_row)
        self._ensure_goal_active(goal_handle)

        def _descend_place() -> None:
            self.motion.descend_to_place()
            self._open_gripper()

        self._run_motion_step(goal_handle, _descend_place)

        self._set_motion_segment(MotionSegment.ASCEND_PLACE, col=to_col, row=to_row)
        self._ensure_goal_active(goal_handle)
        self._run_motion_step(goal_handle, lambda: self.motion.ascend_to_travel(slow=False))

    def execute_move(self, goal_handle):
        self._execute_in_progress = True
        self._safety_gate.clear_cancel()
        self._safety_gate.resume()
        self._replay_attempts = 0
        try:
            return self._execute_move_impl(goal_handle)
        finally:
            self._execute_in_progress = False
            self._motion_segment = MotionSegment.NONE
            self._segment_ctx = {}

    def _execute_move_impl(self, goal_handle):
        move = goal_handle.request.move
        from_col = int(move.from_square.col)
        from_row = int(move.from_square.row)
        to_col = int(move.to_square.col)
        to_row = int(move.to_square.row)
        from_name = f'{chr(ord("a") + from_col)}{from_row + 1}'
        to_name = f'{chr(ord("a") + to_col)}{to_row + 1}'
        raw_uci = f'{from_name}{to_name}{move.promotion or ""}'

        validation = self.board.validate_uci(raw_uci)
        if not validation.ok:
            goal_handle.abort()
            result = ExecuteMove.Result()
            result.success = False
            result.message = validation.message
            return result
        # No separate robot-turn/robot-piece re-check here — validate_uci() already
        # requires the move be legal for whoever's turn self.board currently shows,
        # which now legitimately includes the human's own turn for voice-assisted
        # moves (see goal_callback()/_ensure_goal_active()).

        feedback = ExecuteMove.Feedback()
        try:
            self._at_observe_pose = False
            is_capture = validation.is_capture
            is_en_passant = validation.is_en_passant or bool(move.is_en_passant)
            is_castling = validation.is_castling or bool(move.is_castling)

            if is_capture and not is_en_passant:
                self._capture_square_to_graveyard(
                    to_col,
                    to_row,
                    goal_handle,
                    feedback,
                    progress_start=5,
                    progress_end=20,
                )

            self._pick_and_place(
                from_col,
                from_row,
                to_col,
                to_row,
                goal_handle,
                feedback,
                progress_pick=30 if is_capture and not is_en_passant else 10,
                progress_place=60 if is_capture and not is_en_passant else 50,
            )

            if is_en_passant:
                cap_col = validation.capture_col
                cap_row = validation.capture_row
                if cap_col == 255 and move.capture_square.col < 8:
                    cap_col = int(move.capture_square.col)
                    cap_row = int(move.capture_square.row)
                self._capture_square_to_graveyard(
                    cap_col,
                    cap_row,
                    goal_handle,
                    feedback,
                    progress_start=65,
                    progress_end=72,
                )

            if is_castling:
                rook_from_col = validation.rook_from_col
                rook_from_row = validation.rook_from_row
                rook_to_col = validation.rook_to_col
                rook_to_row = validation.rook_to_row
                if rook_from_col == 255 and move.rook_from.col < 8:
                    rook_from_col = int(move.rook_from.col)
                    rook_from_row = int(move.rook_from.row)
                    rook_to_col = int(move.rook_to.col)
                    rook_to_row = int(move.rook_to.row)
                self._pick_and_place(
                    rook_from_col,
                    rook_from_row,
                    rook_to_col,
                    rook_to_row,
                    goal_handle,
                    feedback,
                    progress_pick=75,
                    progress_place=85,
                )

            feedback.progress = 90
            feedback.status = 'returning home'
            goal_handle.publish_feedback(feedback)
            self._go_home()

            self.board.apply_uci(validation.full_uci)
            self._publish_board_state('move completed')

            feedback.progress = 100
            feedback.status = 'done'
            goal_handle.publish_feedback(feedback)

            goal_handle.succeed()
            result = ExecuteMove.Result()
            result.success = True
            result.message = 'move completed'
            return result
        except RuntimeError as exc:
            msg = str(exc)
            if msg in ('canceled', 'safety gate canceled'):
                # goal_handle.canceled() already called at the raise site.
                result = ExecuteMove.Result()
                result.success = False
                result.message = 'canceled'
                return result
            if msg in ('not robot turn', 'too many hand interruptions'):
                # goal_handle.abort() already called at the raise site.
                result = ExecuteMove.Result()
                result.success = False
                result.message = msg
                return result
            # Any other RuntimeError (e.g. "movel rejected by controller" from a
            # DSR command the safety/velocity limits refused) has NOT yet
            # terminated the goal — fall through to the same abort+fail handling
            # as an unexpected exception instead of letting it escape uncaught
            # (which used to leave the goal in limbo with no clean Result, same
            # class of bug as the recursion crash this replaced).
            self.get_logger().error(f'move failed: {exc}')
            goal_handle.abort()
            result = ExecuteMove.Result()
            result.success = False
            result.message = msg
            return result
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'move failed: {exc}')
            goal_handle.abort()
            result = ExecuteMove.Result()
            result.success = False
            result.message = str(exc)
            return result

    def _restore_move_needs_graveyard(self, move: RestoreMove) -> bool:
        return move.kind in ('graveyard_to_board', 'board_to_graveyard')

    def _execute_restore_move(self, move: RestoreMove) -> None:
        gy_side = (
            self._robot_graveyard_side() if move.graveyard_id == 'robot' else self._human_graveyard_side()
        )
        graveyard_map = None
        if self._restore_move_needs_graveyard(move):
            graveyard_map = self._graveyard_pose_map_for(gy_side)

        self._open_gripper()
        if move.kind == 'graveyard_to_board':
            # pick_piece_at(pose_map=graveyard_map) would immediately re-level to
            # the graveyard's own (potentially lower) travel height as its first
            # step, at whatever XY the arm is coming from — often still over the
            # board from the previous restore move — and cross the rest of the
            # board at that unsafe height to reach the graveyard slot. Ensure
            # board-safe height first, cross to the graveyard slot's XY at that
            # height, and only switch down to the graveyard's calibration once
            # already positioned there.
            self.motion.ensure_travel_height(self.pose_map)
            self.motion.move_xy_at_height(
                move.from_col, move.from_row, graveyard_map, self.pose_map.z_travel_mm
            )
            self.motion.ensure_travel_height(graveyard_map)
            self.motion.descend_to_pick(graveyard_map)
            self._close_gripper()
            self.motion.ascend_to_travel(pose_map=graveyard_map)
            self.motion.ensure_travel_height(self.pose_map)
            self.motion.place_piece_at(
                move.to_col,
                move.to_row,
                self._open_gripper,
                pose_map=self.pose_map,
            )
        elif move.kind == 'board_to_graveyard':
            self.motion.pick_piece_at(move.from_col, move.from_row, self._close_gripper)
            # pick_piece_at ends at the board's travel height over the board
            # pick square. place_piece_at(pose_map=graveyard_map) would
            # immediately re-level to the *graveyard's* travel height (its own
            # first step) before flying to the graveyard slot — crossing back
            # over the rest of the board at that potentially lower/uncleared
            # height and risking a collision with pieces still on it. Cross at
            # the board-safe height instead, and only switch down to the
            # graveyard's own calibration once already positioned over the slot.
            self.motion.move_xy_at_height(
                move.to_col, move.to_row, graveyard_map, self.pose_map.z_travel_mm
            )
            self.motion.ensure_travel_height(graveyard_map)
            self.motion.descend_to_place(graveyard_map)
            self._open_gripper()
            self.motion.ascend_to_travel(slow=False, pose_map=graveyard_map)
        elif move.kind == 'board_to_board':
            self.motion.pick_piece_at(move.from_col, move.from_row, self._close_gripper)
            self.motion.place_piece_at(move.to_col, move.to_row, self._open_gripper)
        else:
            raise ValueError(f'unknown restore move kind: {move.kind}')

        apply_restore_move_to_state(
            self.board,
            self.robot_graveyard,
            move,
            human_graveyard=self.human_graveyard,
        )

    def execute_restore_board(self, goal_handle):
        feedback = RestoreBoard.Feedback()
        result = RestoreBoard.Result()
        try:
            needs = board_needs_restore(self.board, self.robot_graveyard, self.human_graveyard)
            agent_log(
                'doosan_pick_place_node.py:execute_restore_board',
                'needs_restore check',
                {
                    'needs_restore': needs,
                    'fen': self.board.fen,
                    'robot_graveyard_slots': list(self.robot_graveyard.slots),
                    'human_graveyard_slots': list(self.human_graveyard.slots),
                },
                hypothesis_id='G',
            )
            if not needs:
                result.success = True
                result.message = 'already at starting position'
                goal_handle.succeed()
                return result

            moves = plan_board_restore(self.board, self.robot_graveyard, self.human_graveyard)
            total = len(moves)
            self.get_logger().info(f'restore board: {total} planned moves')
            agent_log(
                'doosan_pick_place_node.py:execute_restore_board',
                'restore plan built',
                {
                    'total_moves': total,
                    'moves': [
                        f'{m.kind}:{m.symbol}:({m.from_col},{m.from_row})->({m.to_col},{m.to_row})'
                        for m in moves
                    ],
                },
                hypothesis_id='G',
            )

            # The arm must reach into the board/graveyard area for every restore
            # move, same as captures — without marking this hand-immune, restore
            # never set _motion_segment at all, so ANY hand-detection blip (even
            # a false positive with no hand actually present) raised
            # MotionInterrupted, which nothing here caught or retried: the whole
            # restore aborted mid-sequence with no way to know how far it got.
            self._motion_segment = MotionSegment.RESTORE
            for index, move in enumerate(moves):
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    result.success = False
                    result.message = 'canceled'
                    return result
                feedback.progress = int((index / max(total, 1)) * 90)
                feedback.status = f'{move.kind} {move.symbol}'
                goal_handle.publish_feedback(feedback)
                self.get_logger().info(
                    f'restore {index + 1}/{total}: {move.kind} {move.symbol} '
                    f'({move.from_col},{move.from_row})->({move.to_col},{move.to_row})'
                )
                self._execute_restore_move(move)

            self.board.reset()
            self.robot_graveyard.reset()
            self.human_graveyard.reset()
            self._graveyard_pose_maps.clear()
            self._reload_graveyard_pose_maps()
            self._go_home()
            self._publish_board_state('board restored to starting position')

            feedback.progress = 100
            feedback.status = 'done'
            goal_handle.publish_feedback(feedback)

            result.success = True
            result.message = f'board restored ({total} moves)'
            agent_log(
                'doosan_pick_place_node.py:execute_restore_board',
                'restore completed',
                {'total_moves': total},
                hypothesis_id='G',
            )
            goal_handle.succeed()
            return result
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'restore board failed: {exc}')
            agent_log(
                'doosan_pick_place_node.py:execute_restore_board',
                'restore FAILED',
                {'error': str(exc)},
                hypothesis_id='G',
            )
            goal_handle.abort()
            result.success = False
            result.message = str(exc)
            return result
        finally:
            self._motion_segment = MotionSegment.NONE

    def _publish_board_state(self, message: str) -> None:
        if not self._should_publish_board_state():
            return
        stamp = self.get_clock().now().to_msg()
        occupancy = BoardOccupancy()
        occupancy.header = Header(stamp=stamp, frame_id='board')
        occupancy.cells = list(self.board.cells)
        occupancy.confidence = [1.0 if occupied else 0.0 for occupied in self.board.cells]

        board_state = BoardState()
        board_state.header = occupancy.header
        board_state.occupancy = occupancy
        board_state.scan_id = 0
        board_state.valid = True
        board_state.message = message
        self.board_pub.publish(board_state)

        snapshot = GameSnapshot()
        snapshot.header = occupancy.header
        snapshot.fen = self.board.fen
        snapshot.white_to_move = True
        snapshot.move_number = 1
        snapshot.mode = 0
        snapshot.game_id = 'manual_test'
        self.snapshot_pub.publish(snapshot)

    def destroy_node(self) -> bool:
        if hasattr(self, '_dsr_node'):
            self._dsr_node.destroy_node()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)

    param_loader = rclpy.create_node('pick_place_node')
    param_loader.declare_parameter('robot_id', 'dsr01')
    param_loader.declare_parameter('robot_model', 'm0609')
    robot_id, robot_model = read_robot_ids_from_node(param_loader)
    param_loader.destroy_node()

    dsr_api = bootstrap_dsr(robot_id, robot_model)
    node = DoosanPickPlaceNode(dsr_api)
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
