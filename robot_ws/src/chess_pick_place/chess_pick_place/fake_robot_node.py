#!/usr/bin/env python3
"""Development fake robot exposing chess robot services and actions."""

from __future__ import annotations

import time

import rclpy
from chess_msgs.action import ExecuteMove
from chess_msgs.msg import BoardOccupancy, BoardState, GameSnapshot
from chess_msgs.srv import MoveToObserve, ResetBoard, RetreatArm
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Header

from chess_robot_motion.board_state_manager import BoardStateManager
from chess_robot_motion.square_pose_map import SquareCoord


class FakeRobotNode(Node):
    def __init__(self) -> None:
        super().__init__('fake_robot_node')
        self.declare_parameter('publish_board_state', True)
        self.declare_parameter('home_joints', [-12.68, 22.54, 36.06, -0.05, 121.43, -12.17])
        self.declare_parameter('discard_joints', [-1.33, -24.77, 109.43, -0.02, 95.34, -1.07])
        self.board = BoardStateManager()
        self.board_pub = self.create_publisher(BoardState, 'chess/board_state', 10)
        self.snapshot_pub = self.create_publisher(GameSnapshot, 'chess/game_snapshot', 10)

        group = ReentrantCallbackGroup()
        self.create_service(ResetBoard, 'chess/reset_board', self.handle_reset, callback_group=group)
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

    def handle_reset(self, request, response):
        del request
        self.board.reset()
        self._publish_board_state('board reset')
        response.success = True
        response.message = 'board reset'
        return response

    def handle_observe(self, request, response):
        del request
        joints = list(self.get_parameter('home_joints').value)
        self.get_logger().info(f'Moved to observation pose (stub): {joints}')
        response.success = True
        response.message = 'observation pose reached'
        return response

    def handle_retreat(self, request, response):
        del request
        self.get_logger().info('Retreated to safe pose (stub)')
        response.success = True
        response.message = 'safe pose reached'
        return response

    def goal_callback(self, goal_request):
        del goal_request
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        del goal_handle
        return CancelResponse.ACCEPT

    def execute_move(self, goal_handle):
        move = goal_handle.request.move
        from_col = int(move.from_square.col)
        from_row = int(move.from_square.row)
        to_col = int(move.to_square.col)
        to_row = int(move.to_square.row)

        validation = self.board.validate_move(
            SquareCoord(col=from_col, row=from_row),
            SquareCoord(col=to_col, row=to_row),
        )
        if not validation.ok:
            goal_handle.abort()
            result = ExecuteMove.Result()
            result.success = False
            result.message = validation.message
            return result

        is_capture = bool(move.is_capture) or validation.is_capture
        if is_capture:
            self.get_logger().info(
                f'Capture: remove piece at ({to_col},{to_row}), discard, then move '
                f'({from_col},{from_row}) -> ({to_col},{to_row}) (stub)'
            )
            discard = list(self.get_parameter('discard_joints').value)
            self.get_logger().info(f'movej discard (stub): {discard}')

        self.get_logger().info(
            f'Executing move ({from_col},{from_row}) -> ({to_col},{to_row}) (stub)'
        )

        feedback = ExecuteMove.Feedback()
        progress_steps = (10, 25, 50, 75, 100) if is_capture else (25, 50, 75, 100)
        for progress in progress_steps:
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result = ExecuteMove.Result()
                result.success = False
                result.message = 'canceled'
                return result
            feedback.progress = progress
            status = 'moving'
            if is_capture:
                if progress <= 10:
                    status = 'removing captured piece'
                elif progress <= 25:
                    status = 'discarding captured piece'
            feedback.status = status
            goal_handle.publish_feedback(feedback)
            time.sleep(0.1)

        self.board.apply_move(
            SquareCoord(col=from_col, row=from_row),
            SquareCoord(col=to_col, row=to_row),
        )
        self._publish_board_state('move completed (stub)')

        goal_handle.succeed()
        result = ExecuteMove.Result()
        result.success = True
        result.message = 'move completed'
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
