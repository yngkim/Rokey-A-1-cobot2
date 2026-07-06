#!/usr/bin/env python3
"""Vision-based game state node: scan occupancy and detect user moves."""

from __future__ import annotations

import threading

import rclpy
from chess_msgs.msg import BoardOccupancy, BoardState, GameSnapshot
from chess_msgs.srv import ApplyRobotMove, ConfirmPlayerMove, MoveToObserve, ScanBoard, ScanInitial
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Header

from chess_web_ui.vision_session import VisionSession


class VisionGameNode(Node):
    def __init__(self) -> None:
        super().__init__('vision_game_node')
        self.declare_parameter('auto_detect_moves', False)
        self.declare_parameter('auto_detect_stable_frames', 4)
        self.session = VisionSession()
        self._busy = False
        self._live_cells: list[bool] | None = None
        self._live_stable = 0

        group = ReentrantCallbackGroup()
        self.scan_client = self.create_client(ScanBoard, 'vision/scan_board', callback_group=group)
        self.observe_client = self.create_client(MoveToObserve, 'robot/move_to_observe', callback_group=group)

        self.board_pub = self.create_publisher(BoardState, 'chess/board_state', 10)
        self.snapshot_pub = self.create_publisher(GameSnapshot, 'chess/game_snapshot', 10)

        self.create_service(ScanInitial, 'chess/scan_initial', self.handle_scan_initial, callback_group=group)
        self.create_service(
            ConfirmPlayerMove,
            'chess/confirm_player_move',
            self.handle_confirm_player_move,
            callback_group=group,
        )
        self.create_service(
            ApplyRobotMove,
            'chess/apply_robot_move',
            self.handle_apply_robot_move,
            callback_group=group,
        )

        self.create_subscription(
            BoardState,
            'vision/live_occupancy',
            self._on_live_occupancy,
            10,
            callback_group=group,
        )

        self.get_logger().info('Vision game node ready')
        self._startup_timer = self.create_timer(1.0, self._publish_startup_state)

    def _publish_startup_state(self) -> None:
        self._publish_state(
            'Reset을 눌러 초기 스캔을 실행하세요',
            cells=None,
            valid=False,
        )
        self._startup_timer.cancel()

    def handle_scan_initial(self, request, response):
        del request
        self.session.reset_game()
        if self._busy:
            response.success = False
            response.message = 'scan already in progress'
            response.board_state = self._make_board_state(valid=False, message=response.message)
            return response

        cells, scan_msg = self._scan_board()
        if cells is None:
            response.success = False
            response.message = scan_msg or 'vision scan failed'
            response.board_state = self._make_board_state(valid=False, message=response.message)
            return response

        outcome = self.session.apply_initial_scan(cells)
        self._publish_state(outcome.message, cells=cells, valid=True)
        response.success = outcome.success
        response.message = outcome.message if outcome.success else f'{outcome.message}; {scan_msg}'
        response.fen = self.session.game.fen
        response.board_state = self._make_board_state(
            valid=outcome.success,
            message=response.message,
            cells=cells,
        )
        return response

    def handle_confirm_player_move(self, request, response):
        del request
        if self._busy:
            response.success = False
            response.message = 'scan already in progress'
            response.board_state = self._make_board_state(valid=False, message=response.message)
            return response

        cells, scan_msg = self._scan_board()
        if cells is None:
            response.success = False
            response.message = scan_msg or 'vision scan failed'
            response.board_state = self._make_board_state(valid=False, message=response.message)
            return response

        outcome = self.session.apply_player_move_scan(cells)
        msg = outcome.message if outcome.success else f'{outcome.message}; {scan_msg}'
        self._publish_state(msg, cells=cells, valid=outcome.success)
        response.success = outcome.success
        response.message = msg
        response.from_square = outcome.from_square
        response.to_square = outcome.to_square
        response.captured_piece = outcome.captured_piece
        response.fen = outcome.fen or self.session.game.fen
        response.board_state = self._make_board_state(
            valid=outcome.success,
            message=msg,
            cells=cells,
        )
        return response

    def _on_live_occupancy(self, msg: BoardState) -> None:
        if not bool(self.get_parameter('auto_detect_moves').value):
            return
        if self._busy or not msg.valid:
            return

        cells = list(msg.occupancy.cells)
        baseline = self.session.baseline_cells()
        if cells == baseline:
            self._live_stable = 0
            self._live_cells = None
            return

        if self._live_cells == cells:
            self._live_stable += 1
        else:
            self._live_cells = cells
            self._live_stable = 1

        need = int(self.get_parameter('auto_detect_stable_frames').value)
        if self._live_stable < need:
            return

        outcome = self.session.apply_player_move_scan(cells)
        self._live_stable = 0
        self._live_cells = None
        if not outcome.success:
            return

        self._publish_state(outcome.message, cells=cells, valid=True)
        self.get_logger().info(
            f'auto-detected move {outcome.from_square} -> {outcome.to_square}'
        )

    def handle_apply_robot_move(self, request, response):
        move = request.move
        self.get_logger().info(
            f'apply_robot_move: ({move.from_square.col},{move.from_square.row})'
            f' -> ({move.to_square.col},{move.to_square.row})'
        )
        outcome = self.session.apply_robot_move(
            int(move.from_square.col),
            int(move.from_square.row),
            int(move.to_square.col),
            int(move.to_square.row),
        )
        cells = outcome.cells if outcome.cells is not None else self.session.previous_cells
        self._publish_state(outcome.message, cells=cells, valid=outcome.success)
        response.success = outcome.success
        response.message = outcome.message
        response.fen = self.session.game.fen
        response.board_state = self._make_board_state(
            valid=outcome.success,
            message=outcome.message,
            cells=cells,
        )
        return response

    def _wait_future(self, future, timeout_sec: float):
        done = threading.Event()

        def _on_done(_future) -> None:
            done.set()

        future.add_done_callback(_on_done)
        if not done.wait(timeout_sec):
            return None
        if future.cancelled():
            return None
        exc = future.exception()
        if exc is not None:
            self.get_logger().error(f'async call failed: {exc}')
            return None
        return future.result()

    def _scan_board(self) -> tuple[list[bool] | None, str]:
        self._busy = True
        try:
            self._call_observe_pose()
            if not self.scan_client.wait_for_service(timeout_sec=3.0):
                msg = 'vision/scan_board unavailable'
                self.get_logger().error(msg)
                self._publish_state(msg, cells=None, valid=False)
                return None, msg

            future = self.scan_client.call_async(ScanBoard.Request())
            result = self._wait_future(future, timeout_sec=30.0)
            if result is None:
                msg = 'scan_board call timed out'
                self.get_logger().error(msg)
                self._publish_state(msg, cells=None, valid=False)
                return None, msg
            cells = list(result.board_state.occupancy.cells)
            if not result.success or not result.board_state.valid:
                msg = result.message or 'scan failed'
                self.get_logger().error(f'scan failed: {msg}')
                self._publish_state(msg, cells=cells, valid=False)
                return None, msg

            return cells, result.message
        finally:
            self._busy = False

    def _call_observe_pose(self) -> bool:
        if not self.observe_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn('robot/move_to_observe unavailable, continuing scan')
            return True

        future = self.observe_client.call_async(MoveToObserve.Request())
        result = self._wait_future(future, timeout_sec=10.0)
        if result is None or not result.success:
            self.get_logger().warn('move_to_observe failed, continuing scan anyway')
            return True
        return True

    def _publish_state(
        self,
        message: str,
        *,
        cells: list[bool] | None,
        valid: bool,
    ) -> None:
        stamp = self.get_clock().now().to_msg()
        board_state = self._make_board_state(valid=valid, message=message, cells=cells)
        self.board_pub.publish(board_state)

        snapshot = GameSnapshot()
        snapshot.header = Header(stamp=stamp, frame_id='board')
        snapshot.fen = self.session.game.fen
        snapshot.white_to_move = self.session.game.white_to_move
        snapshot.move_number = self.session.game.move_number
        snapshot.mode = self.session.game.mode
        snapshot.game_id = 'vision_manual'
        self.snapshot_pub.publish(snapshot)

    def _make_board_state(
        self,
        *,
        valid: bool,
        message: str,
        cells: list[bool] | None = None,
    ) -> BoardState:
        stamp = self.get_clock().now().to_msg()
        occupancy = BoardOccupancy()
        occupancy.header = Header(stamp=stamp, frame_id='board')
        if cells is not None:
            occupancy.cells = list(cells)
            occupancy.confidence = [1.0 if c else 0.0 for c in cells]
        elif self.session.previous_cells is not None:
            occupancy.cells = list(self.session.previous_cells)
            occupancy.confidence = [1.0 if c else 0.0 for c in occupancy.cells]
        else:
            occupancy.cells = [False] * 64
            occupancy.confidence = [0.0] * 64

        board_state = BoardState()
        board_state.header = occupancy.header
        board_state.occupancy = occupancy
        board_state.scan_id = self.session.scan_id
        board_state.valid = valid
        board_state.message = message
        return board_state


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VisionGameNode()
    executor = MultiThreadedExecutor(num_threads=4)
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
