#!/usr/bin/env python3
"""ROS2 node stub for chess engine integration."""

import rclpy
from rclpy.node import Node

from chess_engine.stockfish_client import StockfishClient


class EngineNode(Node):
    def __init__(self) -> None:
        super().__init__('engine_node')
        self.client = StockfishClient()
        self.declare_parameter('engine_path', 'stockfish')
        self.declare_parameter('depth', 10)
        self.get_logger().info('Engine node ready (stub library node)')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = EngineNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.client.stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
