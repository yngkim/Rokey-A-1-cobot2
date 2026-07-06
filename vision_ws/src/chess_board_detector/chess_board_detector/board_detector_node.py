#!/usr/bin/env python3
"""ROS2 node stub for chess board detection."""

import rclpy
from rclpy.node import Node

from chess_board_detector.board_detector import BoardDetector


class BoardDetectorNode(Node):
    def __init__(self) -> None:
        super().__init__('board_detector_node')
        self.detector = BoardDetector()
        self.get_logger().info('Board detector node ready (stub)')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BoardDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
