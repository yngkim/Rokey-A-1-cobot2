#!/usr/bin/env python3
"""Doosan M0609 + RG2 chess pick-and-place node (no vision)."""

from __future__ import annotations

import sys
import time

import rclpy
from chess_msgs.action import ExecuteMove, RestoreBoard
from chess_msgs.msg import BoardOccupancy, BoardState, GameSnapshot
from chess_msgs.srv import ResetBoard, RetreatArm, MoveToObserve, SetBoard
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Header

from chess_robot_motion.board_restore_planner import RestoreMove
from chess_robot_motion.board_state_manager import BoardStateManager
from chess_robot_motion.graveyard_pose_map import GraveyardPoseMap, graveyard_slot_name
from chess_robot_motion.graveyard_state import GraveyardState
from chess_robot_motion.motion_planner import ZFirstMotionPlanner
from chess_robot_motion.square_pose_map import CalibratedSquarePoseMap, SquareCoord
from chess_pick_place.dsr_bootstrap import DsrApi, bootstrap_dsr, read_robot_ids_from_node
from chess_pick_place.restore_board import apply_restore_move_to_state, board_needs_restore, plan_board_restore


from robot_control.onrobot import RG


class DoosanPickPlaceNode(Node):
    def __init__(self, dsr_api: DsrApi) -> None:
        super().__init__('pick_place_node')
        self._declare_parameters()
        self._dsr_node = dsr_api.node
        self._movej = dsr_api.movej
        self._movel = dsr_api.movel
        self._mwait = dsr_api.mwait
        self._get_current_posx = dsr_api.get_current_posx
        self._init_gripper()

        self.board = BoardStateManager()
        self.robot_graveyard = GraveyardState(side=self._robot_color())
        self.human_graveyard = GraveyardState(side=self._human_graveyard_side())
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
        )
        self.get_logger().info(
            f'A1 pick pose: xy={self.pose_map.anchor_x},{self.pose_map.anchor_y} '
            f'z_pick={self.pose_map.z_pick_mm} z_travel={self.pose_map.z_travel_mm} '
            f'ori={self.pose_map.fixed_orientation}'
        )
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
        )

        self.board_pub = self.create_publisher(BoardState, 'chess/board_state', 10)
        self.snapshot_pub = self.create_publisher(GameSnapshot, 'chess/game_snapshot', 10)

        group = ReentrantCallbackGroup()
        self.create_service(ResetBoard, 'chess/reset_board', self.handle_reset, callback_group=group)
        self.create_service(SetBoard, 'robot/set_board', self.handle_set_board, callback_group=group)
        self.create_service(MoveToObserve, 'robot/move_to_observe', self.handle_observe, callback_group=group)
        self.create_service(RetreatArm, 'robot/retreat_arm', self.handle_retreat, callback_group=group)
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
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=group,
        )

        self._publish_board_state('board initialized')
        self._go_home()
        self.get_logger().info(
            f'graveyard enabled={self._graveyard_enabled()} '
            f'robot_color={self._robot_color()}'
        )
        self.get_logger().info('Doosan pick-place node ready (at home)')

    def _should_publish_board_state(self) -> bool:
        return bool(self.get_parameter('publish_board_state').value)

    def _home_vel(self) -> float:
        return float(self.get_parameter('home_velocity').value)

    def _home_acc(self) -> float:
        return float(self.get_parameter('home_acceleration').value)

    def _go_home(self) -> None:
        joints = list(self.get_parameter('home_joints').value)
        self.get_logger().info(f'movej home: {joints}')
        self._movej(joints, vel=self._home_vel(), acc=self._home_acc())
        self._mwait()

    def _use_graveyard_for_capture(self, captured_symbol: str | None) -> bool:
        del captured_symbol
        return self._graveyard_enabled()

    def _graveyard_enabled(self) -> bool:
        return bool(self.get_parameter('graveyard_enabled').value)

    def _robot_color(self) -> str:
        return str(self.get_parameter('robot_color').value).strip().lower()

    def _resolve_captured_symbol(self, captured_symbol: str | None) -> str:
        if captured_symbol:
            return captured_symbol
        default = 'p' if self._robot_color() == 'white' else 'P'
        self.get_logger().warn(
            f'capture piece symbol unknown from local FEN; defaulting to {default} for graveyard'
        )
        return default

    def _human_graveyard_side(self) -> str:
        return 'white' if self._robot_color() == 'black' else 'black'

    def _calibrate_graveyard(self, side: str, *, return_home: bool = True) -> None:
        side = side.strip().lower()
        if side in self._graveyard_pose_maps:
            if return_home:
                self._go_home()
            return
        if side == 'white':
            joints = list(self.get_parameter('graveyard_a0_joints').value)
            anchor_name = 'a0'
            col_step = float(self.get_parameter('white_graveyard_col_step_mm').value)
            row_step = float(self.get_parameter('white_graveyard_row_step_mm').value)
            anchor_col = 0
        else:
            joints = list(self.get_parameter('graveyard_h9_joints').value)
            anchor_name = 'h9'
            col_step = float(self.get_parameter('graveyard_col_step_mm').value)
            row_step = float(self.get_parameter('graveyard_row_step_mm').value)
            anchor_col = 7
        self.get_logger().info(f'graveyard calibration: movej {anchor_name} {joints}')
        self._movej(joints, vel=self._home_vel(), acc=self._home_acc())
        self._mwait()
        anchor = list(self._get_current_posx()[0])
        z_pick = self.get_parameter('graveyard_z_pick_mm').value
        z_travel = self.get_parameter('graveyard_z_travel_mm').value
        z_pick_mm = float(z_pick) if z_pick is not None and float(z_pick) > 0 else self.pose_map.z_pick_mm
        z_travel_mm = (
            float(z_travel) if z_travel is not None and float(z_travel) > 0 else self.pose_map.z_travel_mm
        )
        pick_offset = float(self.get_parameter('graveyard_z_pick_offset_mm').value)
        if pick_offset == 0.0:
            pick_offset = float(self.get_parameter('graveyard_z_offset_mm').value)
        travel_extra = float(self.get_parameter('graveyard_z_travel_extra_mm').value)
        if side == 'black':
            z_pick_mm += pick_offset
        z_travel_mm += travel_extra
        self._graveyard_pose_maps[side] = GraveyardPoseMap(
            anchor_h9_posx=anchor,
            col_step_mm=col_step,
            row_step_mm=row_step,
            anchor_col=anchor_col,
            z_pick_mm=z_pick_mm,
            z_travel_mm=z_travel_mm,
        )
        pose_map = self._graveyard_pose_maps[side]
        self.get_logger().info(
            f'graveyard {anchor_name} anchor: xy={pose_map.anchor_x},'
            f'{pose_map.anchor_y} z_pick={pose_map.z_pick_mm} '
            f'z_travel={pose_map.z_travel_mm}'
        )
        if return_home:
            self._go_home()

    def _ensure_graveyard_calibrated(self, side: str, *, return_home: bool = True) -> None:
        if side not in self._graveyard_pose_maps:
            self._calibrate_graveyard(side, return_home=return_home)

    def _graveyard_pose_map_for(self, side: str) -> GraveyardPoseMap:
        self._ensure_graveyard_calibrated(side, return_home=False)
        return self._graveyard_pose_maps[side]

    def _place_captured_in_graveyard(self, captured_symbol: str) -> None:
        side = self._robot_color()
        pose_map = self._graveyard_pose_map_for(side)
        if self.robot_graveyard.is_full():
            raise RuntimeError('graveyard full (16 slots occupied)')
        slot = self.robot_graveyard.next_empty_slot()
        if slot is None:
            raise RuntimeError('graveyard full (no empty slot)')
        grave_col, grave_row = slot
        slot_name = graveyard_slot_name(grave_col, grave_row, side=side)
        self.get_logger().info(f'graveyard place {slot_name} ({captured_symbol})')
        self.motion.place_piece_at(
            grave_col,
            grave_row,
            self._open_gripper,
            pose_map=pose_map,
        )
        self.robot_graveyard.place_piece(grave_col, grave_row, captured_symbol)
        self.get_logger().info(f'graveyard state: {self.robot_graveyard.summary()}')

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
        self.declare_parameter('home_joints', [-12.68, 22.54, 36.06, -0.05, 121.43, -12.17])
        self.declare_parameter('publish_board_state', True)
        self.declare_parameter('robot_color', 'black')
        self.declare_parameter('graveyard_enabled', True)
        self.declare_parameter('graveyard_h9_joints', [-37.12, 8.08, 106.52, -0.02, 65.41, -36.25])
        self.declare_parameter('graveyard_square_mm', 40.0)
        self.declare_parameter('graveyard_col_step_mm', -40.0)
        self.declare_parameter('graveyard_row_step_mm', 40.0)
        self.declare_parameter('graveyard_z_pick_mm', 0.0)
        self.declare_parameter('graveyard_z_travel_mm', 0.0)
        self.declare_parameter('graveyard_z_offset_mm', 0.0)  # deprecated: use graveyard_z_pick_offset_mm
        self.declare_parameter('graveyard_z_pick_offset_mm', 0.0)
        self.declare_parameter('graveyard_z_travel_extra_mm', 30.0)
        self.declare_parameter('graveyard_a0_joints', [19.87, 41.8, 56.67, -0.03, 81.53, 19.86])
        self.declare_parameter('white_graveyard_col_step_mm', 40.0)
        self.declare_parameter('white_graveyard_row_step_mm', -40.0)

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
        del goal_request
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        del goal_handle
        return CancelResponse.ACCEPT

    def handle_reset(self, request, response):
        del request
        self.board.reset()
        self.robot_graveyard.reset()
        self.human_graveyard.reset()
        self._graveyard_pose_maps.clear()
        self._open_gripper()
        self._go_home()
        self._publish_board_state('board reset to starting position')
        response.success = True
        response.message = 'board reset'
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
            response.success = True
            response.message = 'robot board synced from FEN'
            response.fen = self.board.fen
        except Exception as exc:  # noqa: BLE001
            response.success = False
            response.message = str(exc)
        return response

    def handle_observe(self, request, response):
        del request
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
        self._ensure_graveyard_calibrated(self._robot_color(), return_home=True)

        feedback.progress = progress_start
        feedback.status = 'removing captured piece'
        goal_handle.publish_feedback(feedback)

        self._open_gripper()
        self.motion.pick_piece_at(col, row, self._close_gripper)

        feedback.progress = progress_end
        feedback.status = 'placing captured piece in graveyard'
        goal_handle.publish_feedback(feedback)

        self._place_captured_in_graveyard(captured_symbol)
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

        self.motion.ensure_travel_height()
        self.motion.move_xy_at_travel(from_col, from_row)

        feedback.status = 'picking'
        goal_handle.publish_feedback(feedback)
        self.motion.descend_to_pick()
        self._close_gripper()
        self.motion.ascend_to_travel()

        feedback.progress = progress_place
        feedback.status = 'travel to place square'
        goal_handle.publish_feedback(feedback)

        self.motion.move_xy_at_travel(to_col, to_row)
        self.motion.descend_to_place()
        self._open_gripper()
        self.motion.ascend_to_travel(slow=False)

    def execute_move(self, goal_handle):
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

        feedback = ExecuteMove.Feedback()
        try:
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
            self._robot_color() if move.graveyard_id == 'robot' else self._human_graveyard_side()
        )
        graveyard_map = None
        if self._restore_move_needs_graveyard(move):
            graveyard_map = self._graveyard_pose_map_for(gy_side)

        self._open_gripper()
        if move.kind == 'graveyard_to_board':
            self.motion.pick_piece_at(
                move.from_col,
                move.from_row,
                self._close_gripper,
                pose_map=graveyard_map,
            )
            self.motion.place_piece_at(move.to_col, move.to_row, self._open_gripper)
        elif move.kind == 'board_to_graveyard':
            self.motion.pick_piece_at(move.from_col, move.from_row, self._close_gripper)
            self.motion.place_piece_at(
                move.to_col,
                move.to_row,
                self._open_gripper,
                pose_map=graveyard_map,
            )
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
            if not board_needs_restore(self.board, self.robot_graveyard, self.human_graveyard):
                result.success = True
                result.message = 'already at starting position'
                goal_handle.succeed()
                return result

            self._ensure_graveyard_calibrated(self._robot_color(), return_home=True)
            self._ensure_graveyard_calibrated(self._human_graveyard_side(), return_home=True)

            moves = plan_board_restore(self.board, self.robot_graveyard, self.human_graveyard)
            total = len(moves)
            self.get_logger().info(f'restore board: {total} planned moves')

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
            self._go_home()
            self._publish_board_state('board restored to starting position')

            feedback.progress = 100
            feedback.status = 'done'
            goal_handle.publish_feedback(feedback)

            result.success = True
            result.message = f'board restored ({total} moves)'
            goal_handle.succeed()
            return result
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'restore board failed: {exc}')
            goal_handle.abort()
            result.success = False
            result.message = str(exc)
            return result

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
    executor.add_node(dsr_api.node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
