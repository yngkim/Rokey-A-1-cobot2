#!/usr/bin/env python3
"""Development fake robot exposing chess robot services and actions."""

from __future__ import annotations

import json
import time

import chess
import rclpy
from chess_msgs.action import ExecuteMove, RestoreBoard
from chess_msgs.msg import BoardOccupancy, BoardState, GameSnapshot
from chess_msgs.srv import MoveToObserve, ResetBoard, RetreatArm, SetBoard, UndoMoves
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool, Header
from std_srvs.srv import Trigger

from chess_robot_motion.safety_gate import SafetyGate

from chess_robot_motion.board_state_manager import BoardStateManager
from chess_robot_motion.graveyard_pose_map import graveyard_slot_name
from chess_robot_motion.graveyard_state import GraveyardState
from chess_robot_motion.move_physics import captured_piece_symbol
from chess_robot_motion.graveyard_sides import robot_chess_color
from chess_robot_motion.undo_move import UndoStep, plan_reverse_physical, plan_reverse_uci
from chess_pick_place.graveyard_sync import (
    apply_human_color_to_graveyards,
    default_human_color_from_robot_param,
    normalize_human_color,
)
from chess_pick_place.restore_board import apply_restore_move_to_state, board_needs_restore, plan_board_restore


class FakeRobotNode(Node):
    def __init__(self) -> None:
        super().__init__('fake_robot_node')
        self.declare_parameter('publish_board_state', True)
        self.declare_parameter('home_joints', [-12.32, 22.41, 36.08, -0.09, 121.46, -13.86])
        self.declare_parameter('robot_color', 'black')
        self.declare_parameter('board_orientation', 'standard')
        self.declare_parameter('graveyard_enabled', True)
        self.declare_parameter('graveyard_a0_joints', [20.12, 41.84, 55.64, -0.03, 82.52, 15.62])
        self.declare_parameter('white_graveyard_col_step_mm', -40.0)
        self.declare_parameter('white_graveyard_row_step_mm', 40.0)
        self._human_color_value = default_human_color_from_robot_param(
            str(self.get_parameter('robot_color').value)
        )
        self.board = BoardStateManager()
        self.robot_graveyard = GraveyardState(side='black')
        self.human_graveyard = GraveyardState(side='white')
        self._sync_graveyard_sides()
        self._safety_gate = SafetyGate()
        self._at_observe_pose = True
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
        self._publish_board_state('fake robot ready')
        self.get_logger().info('Fake robot node ready')

    def _should_publish_board_state(self) -> bool:
        return bool(self.get_parameter('publish_board_state').value)

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
        self._human_color_value = color
        self._sync_graveyard_sides()

    def _graveyard_enabled(self) -> bool:
        return bool(self.get_parameter('graveyard_enabled').value)

    def _robot_color(self) -> str:
        return robot_chess_color(self._human_color())

    def _is_robot_turn(self) -> bool:
        board = chess.Board(self.board.fen)
        robot_is_white = self._robot_color() == 'white'
        return board.turn == chess.WHITE if robot_is_white else board.turn == chess.BLACK

    def _use_graveyard_for_capture(self, captured_symbol: str | None) -> bool:
        del captured_symbol
        return self._graveyard_enabled()

    def _resolve_captured_symbol(self, captured_symbol: str | None) -> str:
        if captured_symbol:
            return captured_symbol
        return 'p' if self._robot_color() == 'white' else 'P'

    def _robot_graveyard_side(self) -> str:
        from chess_robot_motion.graveyard_sides import robot_graveyard_side

        return robot_graveyard_side(self._human_color())

    def _human_graveyard_side(self) -> str:
        from chess_robot_motion.graveyard_sides import human_graveyard_side

        return human_graveyard_side(self._human_color())

    def _place_captured_in_graveyard_stub(self, captured_symbol: str) -> None:
        if self.robot_graveyard.is_full():
            raise RuntimeError('graveyard full (16 slots occupied)')
        slot = self.robot_graveyard.next_empty_slot()
        if slot is None:
            raise RuntimeError('graveyard full (no empty slot)')
        grave_col, grave_row = slot
        slot_name = graveyard_slot_name(grave_col, grave_row, side=self._robot_graveyard_side())
        self.get_logger().info(f'graveyard place {slot_name} ({captured_symbol}) (stub)')
        self.robot_graveyard.place_piece(grave_col, grave_row, captured_symbol)
        self.get_logger().info(f'graveyard state: {self.robot_graveyard.summary()}')

    def handle_reset(self, request, response):
        del request
        self._safety_gate.resume()
        self.board.reset()
        self.robot_graveyard.reset()
        self.human_graveyard.reset()
        self._publish_board_state('board reset')
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
            human_color = getattr(request, 'human_color', '') or ''
            if human_color.strip():
                self._set_human_color(human_color)
            orientation = getattr(request, 'board_orientation', '') or ''
            if orientation.strip():
                self.set_parameters([
                    rclpy.parameter.Parameter(
                        'board_orientation',
                        rclpy.parameter.Parameter.Type.STRING,
                        orientation.strip().lower(),
                    )
                ])
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

    def _execute_undo_step_stub(self, step: UndoStep) -> None:
        if step.kind == 'board_to_board':
            symbol = self.board.remove_piece_at(step.from_col, step.from_row)
            if symbol is not None:
                self.board.put_piece_at(step.to_col, step.to_row, symbol)
            return
        if step.kind == 'graveyard_to_board':
            if not step.graveyard_side:
                raise RuntimeError('graveyard_to_board step missing graveyard_side')
            gy = self._graveyard_for_side(step.graveyard_side)
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
                self.get_logger().info(f'undo {label}: {len(steps)} steps (stub)')
                for step in steps:
                    self._execute_undo_step_stub(step)
                time.sleep(0.02)
            oldest = moves[-1]
            self.board.set_fen(str(oldest.get('fen_before', '')).strip())
            self._publish_board_state('undo moves completed (stub)')
            response.success = True
            response.message = f'undid {len(moves)} move(s) stub'
            return response
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'undo moves failed: {exc}')
            response.success = False
            response.message = str(exc)
            return response

    def handle_observe(self, request, response):
        del request
        if self._at_observe_pose:
            self.get_logger().info('move_to_observe: already at observe/home (stub)')
        else:
            joints = list(self.get_parameter('home_joints').value)
            self.get_logger().info(f'Moved to observation pose (stub): {joints}')
            self._at_observe_pose = True
        response.success = True
        response.message = 'observation pose reached'
        return response

    def handle_retreat(self, request, response):
        del request
        self.get_logger().info('Retreated to safe pose (stub)')
        response.success = True
        response.message = 'safe pose reached'
        return response

    def handle_user_stop(self, request, response):
        del request
        self._safety_gate.request_pause()
        self.get_logger().info('user stop — motion halted (stub)')
        response.success = True
        response.message = 'stopped'
        return response

    def handle_user_stop_resume(self, request, response):
        del request
        self._safety_gate.resume()
        self.get_logger().info('user stop resume — motion gate open (stub)')
        response.success = True
        response.message = 'resumed'
        return response

    def handle_user_stop_abort(self, request, response):
        del request
        self._safety_gate.request_cancel()
        self._safety_gate.clear_cancel()
        self._safety_gate.resume()
        self.get_logger().info('user stop abort — canceled (stub)')
        response.success = True
        response.message = 'aborted'
        return response

    def goal_callback(self, goal_request):
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
        # No robot-turn/robot-piece re-check — validate_uci() already requires the
        # move be legal for whoever's turn self.board shows, which now legitimately
        # includes the human's own turn for voice-assisted moves (see the matching
        # fix in doosan_pick_place_node.py).
        return GoalResponse.ACCEPT

    def restore_goal_callback(self, goal_request):
        # RestoreBoard.Goal has no fields — must not reuse execute_move's
        # goal_callback, which unconditionally reads goal_request.move (an
        # ExecuteMove-only field) and would raise AttributeError here.
        del goal_request
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        del goal_handle
        return CancelResponse.ACCEPT

    def _on_hand_in_board(self, msg: Bool) -> None:
        if msg.data:
            self._safety_gate.request_pause()
        else:
            self._safety_gate.resume()

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
        # No robot-turn/robot-piece re-check here either — see goal_callback().

        self._at_observe_pose = False

        is_capture = validation.is_capture
        is_en_passant = validation.is_en_passant or bool(move.is_en_passant)

        if is_capture and not is_en_passant:
            board = chess.Board(self.board.fen)
            captured_move = chess.Move.from_uci(validation.full_uci)
            symbol = captured_piece_symbol(board, captured_move)
            if not self._use_graveyard_for_capture(symbol):
                goal_handle.abort()
                result = ExecuteMove.Result()
                result.success = False
                result.message = 'graveyard disabled; cannot capture piece'
                return result
            if symbol:
                self._place_captured_in_graveyard_stub(symbol)

        if is_en_passant:
            board = chess.Board(self.board.fen)
            captured_move = chess.Move.from_uci(validation.full_uci)
            symbol = captured_piece_symbol(board, captured_move)
            if symbol:
                self._place_captured_in_graveyard_stub(symbol)

        self.get_logger().info(
            f'Executing move ({from_col},{from_row}) -> ({to_col},{to_row}) (stub)'
        )

        feedback = ExecuteMove.Feedback()
        progress_steps = (10, 25, 50, 75, 100) if is_capture and not is_en_passant else (25, 50, 75, 100)
        for progress in progress_steps:
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result = ExecuteMove.Result()
                result.success = False
                result.message = 'canceled'
                return result
            try:
                self._safety_gate.wait_if_paused()
            except RuntimeError:
                goal_handle.canceled()
                result = ExecuteMove.Result()
                result.success = False
                result.message = 'canceled'
                return result
            feedback.progress = progress
            feedback.status = 'moving'
            goal_handle.publish_feedback(feedback)
            time.sleep(0.1)

        self.board.apply_uci(validation.full_uci)
        self._publish_board_state('move completed (stub)')

        goal_handle.succeed()
        result = ExecuteMove.Result()
        result.success = True
        result.message = 'move completed'
        self._at_observe_pose = True
        return result

    def execute_restore_board(self, goal_handle):
        feedback = RestoreBoard.Feedback()
        result = RestoreBoard.Result()
        try:
            if not board_needs_restore(self.board, self.robot_graveyard, self.human_graveyard):
                result.success = True
                result.message = 'already at starting position'
                goal_handle.succeed()
                return result

            moves = plan_board_restore(self.board, self.robot_graveyard, self.human_graveyard)
            total = len(moves)
            self.get_logger().info(f'restore board (stub): {total} planned moves')

            for index, move in enumerate(moves):
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    result.success = False
                    result.message = 'canceled'
                    return result
                feedback.progress = int((index / max(total, 1)) * 90)
                feedback.status = f'{move.kind} {move.symbol} (stub)'
                goal_handle.publish_feedback(feedback)
                self.get_logger().info(
                    f'restore {index + 1}/{total}: {move.kind} {move.symbol} (stub)'
                )
                apply_restore_move_to_state(
                    self.board,
                    self.robot_graveyard,
                    move,
                    human_graveyard=self.human_graveyard,
                )
                time.sleep(0.05)

            self.board.reset()
            self.robot_graveyard.reset()
            self.human_graveyard.reset()
            self._publish_board_state('board restored (stub)')

            feedback.progress = 100
            feedback.status = 'done'
            goal_handle.publish_feedback(feedback)

            result.success = True
            result.message = f'board restored ({total} moves, stub)'
            goal_handle.succeed()
            return result
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'restore board failed: {exc}')
            goal_handle.abort()
            result.success = False
            result.message = str(exc)
            return result


def main(args=None) -> None:
    rclpy.init(args=args)
    node = FakeRobotNode()
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
