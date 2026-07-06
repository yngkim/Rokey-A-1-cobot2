#!/usr/bin/env python3
"""Side-view chess piece detection node."""

from __future__ import annotations

import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image

from chess_piece_classifier.camera_source import CameraBuffer
from chess_piece_classifier.chess_detector import ChessPieceDetector


class PieceClassifierNode(Node):
    def __init__(self) -> None:
        super().__init__('piece_classifier_node')
        self.declare_parameter('camera_source', 'webcam')
        self.declare_parameter('camera_topic', '')
        self.declare_parameter('webcam_device', 1)
        self.declare_parameter('camera_width', 1920)
        self.declare_parameter('camera_height', 1080)
        self.declare_parameter('model_path', 'yamero999/chess-piece-detection-yolo11n')
        self.declare_parameter('conf_threshold', 0.45)
        self.declare_parameter('iou_threshold', 0.5)
        self.declare_parameter('imgsz', 416)
        self.declare_parameter('device', '')
        self.declare_parameter('publish_debug_image', True)
        self.declare_parameter('debug_image_topic', 'vision/debug/side_view')
        self.declare_parameter('publish_rate_hz', 2.0)

        self.bridge = CvBridge()
        self.detector = ChessPieceDetector(
            model_path=self.get_parameter('model_path').value,
            conf=float(self.get_parameter('conf_threshold').value),
            iou=float(self.get_parameter('iou_threshold').value),
            imgsz=int(self.get_parameter('imgsz').value),
            device=self.get_parameter('device').value,
        )
        topic = self.get_parameter('camera_topic').value
        if not topic:
            topic = '/camera/camera/color/image_raw'
        self.camera = CameraBuffer(
            self,
            source=self.get_parameter('camera_source').value,
            topic=topic,
            device_id=int(self.get_parameter('webcam_device').value),
            width=int(self.get_parameter('camera_width').value),
            height=int(self.get_parameter('camera_height').value),
        )
        self.debug_pub = None
        if self.get_parameter('publish_debug_image').value:
            self.debug_pub = self.create_publisher(
                Image,
                self.get_parameter('debug_image_topic').value,
                10,
            )

        period = 1.0 / max(float(self.get_parameter('publish_rate_hz').value), 0.1)
        self.timer = self.create_timer(period, self._on_timer)
        self.get_logger().info('Piece classifier node ready')

    def _on_timer(self) -> None:
        frame = self.camera.get_frame()
        if frame is None:
            return

        detections = self.detector.detect(frame)
        self.get_logger().info(
            f'Side camera detections: {len(detections)}',
            throttle_duration_sec=2.0,
        )
        if self.debug_pub is None:
            return

        annotated = self.detector.annotate(frame, detections)
        self.debug_pub.publish(self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8'))

    def destroy_node(self) -> bool:
        self.camera.destroy()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PieceClassifierNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
