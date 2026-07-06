#!/usr/bin/env python3
"""ROS2 orchestrator node coordinating vision, robot, and game logic."""

from __future__ import annotations

import chess

import rclpy
from action_msgs.msg import GoalStatus
from chess_msgs.action import ExecuteMove
from chess_msgs.msg import ChessMove, GameSnapshot, Square
from chess_msgs.srv import MoveToObserve, RetreatArm, ScanBoard
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import Empty, Header

from chess_orchestrator.game_phase import GamePhase
from chess_orchestrator.orchestrator_core import OrchestratorCore


class OrchestratorNode(Node):
    def __init__(self) -> None:
        super().__init__('orchestrator_node')
        self.core = OrchestratorCore()
        self.core.start_new_game()

        self.scan_client = self.create_client(ScanBoard, 'vision/scan_board')
        self.observe_client = self.create_client(MoveToObserve, 'robot/move_to_observe')
        self.retreat_client = self.create_client(RetreatArm, 'robot/retreat_arm')
        self.execute_client = ActionClient(self, ExecuteMove, 'robot/execute_move')

        self.snapshot_pub = self.create_publisher(GameSnapshot, 'chess/game_snapshot', 10)
        self.create_subscription(Empty, 'chess/user_move_confirmed', self.on_user_move_confirmed, 10)

        self.get_logger().info('Orchestrator node ready')

    def on_user_move_confirmed(self, _msg: Empty) -> None:
        if self.core.phase != GamePhase.WAIT_USER_MOVE:
            self.get_logger().warn('User confirm ignored: not waiting for user move')
            return
        self.core.on_user_confirmed()
        self._begin_user_scan()

    def _begin_user_scan(self) -> None:
        if not self._call_observe_pose():
            return
        self._request_scan()

    def _call_observe_pose(self) -> bool:
        if not self.observe_client.wait_for_service(timeout_sec=0.5):
            self.get_logger().warn('robot/move_to_observe unavailable, continuing')
            return True
        future = self.observe_client.call_async(MoveToObserve.Request())
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        if future.result() is None or not future.result().success:
            self.get_logger().error('Failed to move arm to observation pose')
            return False
        return True

    def _request_scan(self) -> None:
        if not self.scan_client.wait_for_service(timeout_sec=2.0):
            self.get_logger().error('vision/scan_board service unavailable')
            self.core.phase = GamePhase.ERROR
            return

        future = self.scan_client.call_async(ScanBoard.Request())
        future.add_done_callback(self._on_scan_done)

    def _on_scan_done(self, future) -> None:
        response = future.result()
        if response is None or not response.success:
            self.get_logger().error('Board scan failed')
            self.core.phase = GamePhase.ERROR
            return

        cells = list(response.board_state.occupancy.cells)
        if self.core.phase == GamePhase.SCANNING_USER:
            self.core.apply_scan(cells)
            self.publish_snapshot()
            if self.core.phase == GamePhase.ROBOT_PLANNING:
                self._execute_robot_turn()
            elif self.core.phase == GamePhase.UI_CONFIRM:
                self.get_logger().warn('Ambiguous user move; waiting for UI confirmation')
        else:
            self.core.apply_scan(cells)
            self.publish_snapshot()

    def _execute_robot_turn(self) -> None:
        uci = self.core.plan_robot_move()
        from_sq = chess.parse_square(uci[0:2])
        to_sq = chess.parse_square(uci[2:4])
        promotion = uci[4:] if len(uci) > 4 else ''

        move = ChessMove()
        move.from_square = Square(col=chess.square_file(from_sq), row=chess.square_rank(from_sq))
        move.to_square = Square(col=chess.square_file(to_sq), row=chess.square_rank(to_sq))
        move.promotion = promotion
        move.is_capture = False

        if not self.execute_client.wait_for_server(timeout_sec=1.0):
            self.get_logger().warn('robot/execute_move unavailable; applying move logically only')
            self.core.game.apply_uci(uci)
            self.core.phase = GamePhase.WAIT_USER_MOVE
            self.publish_snapshot()
            return

        goal = ExecuteMove.Goal()
        goal.move = move
        send_future = self.execute_client.send_goal_async(goal)
        send_future.add_done_callback(self._on_execute_goal_sent)

    def _on_execute_goal_sent(self, future) -> None:
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Robot move goal rejected')
            self.core.phase = GamePhase.ERROR
            return
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_execute_done)

    def _on_execute_done(self, future) -> None:
        result = future.result().result
        status = future.result().status
        success = status == GoalStatus.STATUS_SUCCEEDED and result.success
        self.core.on_robot_move_finished(success)
        if success:
            self._request_scan()
        else:
            self.get_logger().error('Robot move failed')

    def publish_snapshot(self) -> None:
        msg = GameSnapshot()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.fen = self.core.game.fen
        msg.white_to_move = self.core.game.white_to_move
        msg.move_number = self.core.game.move_number
        msg.mode = self.core.game.mode
        msg.game_id = 'default'
        self.snapshot_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = OrchestratorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.core.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
