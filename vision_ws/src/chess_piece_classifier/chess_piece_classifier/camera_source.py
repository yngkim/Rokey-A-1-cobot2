"""Camera input helpers for ROS image topics, RealSense (cobot2_ws), and webcams."""

from __future__ import annotations

import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image

from chess_piece_classifier.realsense import ImgNode


class CameraBuffer:
    def __init__(
        self,
        node: Node,
        source: str = 'topic',
        topic: str = '/camera/camera/color/image_raw',
        device_id: int = 0,
        width: int = 1280,
        height: int = 720,
    ) -> None:
        self.node = node
        self.source = source
        self.topic = topic
        self.device_id = device_id
        self.width = width
        self.height = height
        self.bridge = CvBridge()
        self._latest_frame: np.ndarray | None = None
        self._capture: cv2.VideoCapture | None = None
        self._subscription = None

        if self.source == 'topic':
            self._subscription = node.create_subscription(
                Image,
                self.topic,
                self._image_callback,
                10,
            )
            node.get_logger().info(f'CameraBuffer subscribed to {self.topic}')
        elif self.source == 'webcam':
            self._open_webcam()
        else:
            raise ValueError(f'Unsupported camera source: {self.source}')

    def _open_webcam(self) -> None:
        self._capture = cv2.VideoCapture(self.device_id)
        if self.width > 0:
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height > 0:
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not self._capture.isOpened():
            raise RuntimeError(f'Failed to open webcam device {self.device_id}')
        self.node.get_logger().info(
            f'CameraBuffer opened webcam device {self.device_id} '
            f'({self.width}x{self.height})'
        )

    def _image_callback(self, msg: Image) -> None:
        try:
            self._latest_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as exc:  # noqa: BLE001
            self.node.get_logger().warn(f'Failed to convert image: {exc}')

    def get_frame(self) -> np.ndarray | None:
        if self.source == 'webcam':
            if self._capture is None:
                return None
            ok, frame = self._capture.read()
            if not ok:
                return None
            self._latest_frame = frame
        return None if self._latest_frame is None else self._latest_frame.copy()

    def wait_for_stable_frames(
        self,
        frame_count: int,
        settling_ms: int,
    ) -> np.ndarray | None:
        if settling_ms > 0:
            time.sleep(settling_ms / 1000.0)

        if self.source == 'topic':
            deadline = time.time() + max(2.0, settling_ms / 1000.0 + 1.0)
            while self._latest_frame is None and time.time() < deadline:
                rclpy.spin_once(self.node, timeout_sec=0.05)
            if self._latest_frame is None:
                return None

        last_frame = None
        stable = 0
        deadline = time.time() + 5.0
        while stable < frame_count and time.time() < deadline:
            frame = self.get_frame()
            if frame is None:
                if self.source == 'topic':
                    rclpy.spin_once(self.node, timeout_sec=0.05)
                continue
            if last_frame is not None and frame.shape == last_frame.shape:
                diff = np.mean(cv2.absdiff(frame, last_frame))
                if diff < 2.0:
                    stable += 1
                else:
                    stable = 0
            last_frame = frame
            time.sleep(0.05)

        return last_frame

    def destroy(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class RealSenseBuffer:
    """cobot2_ws ImgNode 기반 RealSense color frame 버퍼."""

    def __init__(self, node: Node) -> None:
        self.node = node
        self._img_node = ImgNode()
        node.get_logger().info(
            'RealSenseBuffer subscribed via cobot2_ws ImgNode '
            '(/camera/camera/color/image_raw)'
        )

    def _spin(self) -> None:
        rclpy.spin_once(self._img_node, timeout_sec=0.05)

    def get_frame(self) -> np.ndarray | None:
        self._spin()
        frame = self._img_node.get_color_frame()
        return None if frame is None else frame.copy()

    def get_depth_frame(self) -> np.ndarray | None:
        self._spin()
        frame = self._img_node.get_depth_frame()
        return None if frame is None else frame.copy()

    def wait_for_stable_frames(
        self,
        frame_count: int,
        settling_ms: int,
    ) -> np.ndarray | None:
        color, _depth = self.wait_for_stable_color_depth(frame_count, settling_ms)
        return color

    def wait_for_stable_color_depth(
        self,
        frame_count: int,
        settling_ms: int,
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        if settling_ms > 0:
            time.sleep(settling_ms / 1000.0)

        deadline = time.time() + max(2.0, settling_ms / 1000.0 + 1.0)
        while self._img_node.get_color_frame() is None and time.time() < deadline:
            self._spin()
        if self._img_node.get_color_frame() is None:
            return None, None

        last_frame = None
        stable = 0
        deadline = time.time() + 5.0
        while stable < frame_count and time.time() < deadline:
            frame = self.get_frame()
            if frame is None:
                self._spin()
                continue
            if last_frame is not None and frame.shape == last_frame.shape:
                diff = np.mean(cv2.absdiff(frame, last_frame))
                if diff < 2.0:
                    stable += 1
                else:
                    stable = 0
            last_frame = frame
            time.sleep(0.05)

        if last_frame is None:
            return None, None
        return last_frame, self.get_depth_frame()

    def destroy(self) -> None:
        self._img_node.destroy_node()


def create_camera_buffer(
    node: Node,
    source: str,
    topic: str = '/camera/camera/color/image_raw',
    device_id: int = 0,
    width: int = 1280,
    height: int = 720,
) -> CameraBuffer | RealSenseBuffer:
    if source == 'realsense':
        return RealSenseBuffer(node)
    return CameraBuffer(
        node,
        source=source,
        topic=topic,
        device_id=device_id,
        width=width,
        height=height,
    )
