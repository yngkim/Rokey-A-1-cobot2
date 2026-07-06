#!/usr/bin/env python3
"""Save a color frame from the running RealSense (observe pose)."""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image


class _CaptureNode(Node):
    def __init__(self) -> None:
        super().__init__('capture_observe_frame')
        self._bridge = CvBridge()
        self._frame = None
        self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self._on_image,
            10,
        )

    def _on_image(self, msg: Image) -> None:
        self._frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')

    def get_frame(self):
        return self._frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Capture RealSense color frame to JPEG')
    parser.add_argument('--output', default='/tmp/frame.jpg', help='Output image path')
    parser.add_argument('--settling-ms', type=int, default=500)
    args = parser.parse_args(argv)

    rclpy.init()
    node = _CaptureNode()
    try:
        if args.settling_ms > 0:
            time.sleep(args.settling_ms / 1000.0)

        deadline = time.time() + 20.0
        frame = None
        while time.time() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            frame = node.get_frame()
            if frame is not None:
                break

        if frame is None:
            print(
                'ERROR: no color frame — start vision_manual first',
                file=sys.stderr,
            )
            return 1

        if not cv2.imwrite(args.output, frame):
            print(f'ERROR: failed to write {args.output}', file=sys.stderr)
            return 1

        h, w = frame.shape[:2]
        print(f'saved {args.output} ({w}x{h})')
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
