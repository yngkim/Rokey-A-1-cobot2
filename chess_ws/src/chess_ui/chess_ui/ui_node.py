#!/usr/bin/env python3
"""Minimal UI bridge node for development and CLI testing."""

from __future__ import annotations

import threading

import rclpy
from chess_msgs.msg import GameSnapshot
from rclpy.node import Node
from std_msgs.msg import Empty


class UiNode(Node):
    def __init__(self) -> None:
        super().__init__('ui_node')
        self.confirm_pub = self.create_publisher(Empty, 'chess/user_move_confirmed', 10)
        self.create_subscription(GameSnapshot, 'chess/game_snapshot', self.on_snapshot, 10)
        self.get_logger().info(
            'UI node ready. Type "confirm" and press Enter to publish user move complete.'
        )
        threading.Thread(target=self._cli_loop, daemon=True).start()

    def on_snapshot(self, msg: GameSnapshot) -> None:
        turn = 'white' if msg.white_to_move else 'black'
        self.get_logger().info(f'Game snapshot | move {msg.move_number} | turn: {turn} | fen: {msg.fen}')

    def _cli_loop(self) -> None:
        while rclpy.ok():
            try:
                command = input('ui> ').strip().lower()
            except EOFError:
                break
            if command in {'confirm', 'done', 'c'}:
                self.confirm_pub.publish(Empty())
                self.get_logger().info('Published user move confirmed')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = UiNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
