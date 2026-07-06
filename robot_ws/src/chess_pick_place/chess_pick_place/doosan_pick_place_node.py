#!/usr/bin/env python3
"""Doosan M0609 + RG2 chess pick-and-place node (no vision)."""

from __future__ import annotations

import sys
import time

import rclpy
from chess_msgs.action import ExecuteMove
from chess_msgs.msg import BoardOccupancy, BoardState, GameSnapshot
from chess_msgs.srv import ResetBoard, RetreatArm, MoveToObserve
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Header

from chess_robot_motion.board_state_manager import BoardStateManager
from chess_robot_motion.motion_planner import ZFirstMotionPlanner
from chess_robot_motion.square_pose_map import CalibratedSquarePoseMap, SquareCoord
from chess_pick_place.dsr_bootstrap import DsrApi, bootstrap_dsr, read_robot_ids_from_node


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

        self._publish_board_state('board initialized')
        self._go_home()
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

    def _go_discard(self) -> None:
        joints = list(self.get_parameter('discard_joints').value)
        self.get_logger().info(f'movej discard: {joints}')
        self._movej(joints, vel=self._home_vel(), acc=self._home_acc())
        self._mwait()

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
        self.declare_parameter('discard_joints', [-1.33, -24.77, 109.43, -0.02, 95.34, -1.07])
        self.declare_parameter('publish_board_state', True)

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
        self._open_gripper()
        self._go_home()
        self._publish_board_state('board reset to starting position')
        response.success = True
        response.message = 'board reset'
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

        feedback = ExecuteMove.Feedback()
        try:
            is_capture = bool(move.is_capture) or validation.is_capture

            if is_capture:
                feedback.progress = 5
                feedback.status = 'removing captured piece'
                goal_handle.publish_feedback(feedback)

                self._open_gripper()
                self.motion.pick_piece_at(to_col, to_row, self._close_gripper)

                feedback.progress = 20
                feedback.status = 'discarding captured piece'
                goal_handle.publish_feedback(feedback)

                self._go_discard()
                self._open_gripper()
                self._go_home()

            self._open_gripper()

            feedback.progress = 30 if is_capture else 10
            feedback.status = 'travel to pick square'
            goal_handle.publish_feedback(feedback)

            self.motion.ensure_travel_height()
            self.motion.move_xy_at_travel(from_col, from_row)

            feedback.progress = 45 if is_capture else 25
            feedback.status = 'picking'
            goal_handle.publish_feedback(feedback)

            self.motion.descend_to_pick()
            self._close_gripper()
            self.motion.ascend_to_travel()

            feedback.progress = 60 if is_capture else 50
            feedback.status = 'travel to place square'
            goal_handle.publish_feedback(feedback)

            self.motion.move_xy_at_travel(to_col, to_row)
            self.motion.descend_to_place()
            self._open_gripper()
            self.motion.ascend_to_travel(slow=True)

            feedback.progress = 80 if is_capture else 75
            feedback.status = 'returning home'
            goal_handle.publish_feedback(feedback)

            self._go_home()

            self.board.apply_move(
                SquareCoord(col=from_col, row=from_row),
                SquareCoord(col=to_col, row=to_row),
            )
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
