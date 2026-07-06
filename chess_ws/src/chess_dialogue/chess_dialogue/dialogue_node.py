#!/usr/bin/env python3
"""Dialogue mode node stub."""

import rclpy
from rclpy.node import Node

from chess_dialogue.dialogue import DialogueService


class DialogueNode(Node):
    def __init__(self) -> None:
        super().__init__('dialogue_node')
        self.dialogue = DialogueService()
        self.get_logger().info('Dialogue node ready (stub)')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DialogueNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
