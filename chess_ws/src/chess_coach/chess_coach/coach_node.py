#!/usr/bin/env python3
"""Coaching mode node stub."""

import rclpy
from rclpy.node import Node

from chess_coach.coach import Coach


class CoachNode(Node):
    def __init__(self) -> None:
        super().__init__('coach_node')
        self.coach = Coach()
        self.get_logger().info('Coach node ready (stub)')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CoachNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.coach.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
