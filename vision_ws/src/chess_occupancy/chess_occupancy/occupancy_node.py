#!/usr/bin/env python3
"""Vision scan service that returns board occupancy snapshots."""

from __future__ import annotations

import rclpy
from chess_msgs.msg import BoardOccupancy, BoardState
from chess_msgs.srv import ScanBoard
from cv_bridge import CvBridge
import numpy as np
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.exceptions import ParameterUninitializedException
from rclpy.node import Node
from rclpy.parameter import ParameterType
from sensor_msgs.msg import Image
from std_msgs.msg import Header

from chess_board_detector.board_detector import BoardDetector
from chess_piece_classifier.camera_source import create_camera_buffer
from chess_occupancy.depth_reference import load_empty_depth_reference
from chess_occupancy.occupancy_grid import starting_occupancy
from chess_occupancy.scan_pipeline import scan_board
from chess_piece_classifier.chess_detector import ChessPieceDetector


class OccupancyNode(Node):
    def __init__(self) -> None:
        super().__init__('occupancy_node')
        self.declare_parameter('camera_source', 'realsense')
        self.declare_parameter('camera_topic', '/camera/camera/color/image_raw')
        self.declare_parameter('webcam_device', 0)
        self.declare_parameter('camera_width', 1280)
        self.declare_parameter('camera_height', 720)
        self.declare_parameter('settling_time_ms', 300)
        self.declare_parameter('stable_frame_count', 3)
        self.declare_parameter('yolo_model_path', 'yamero999/chess-piece-detection-yolo11n')
        self.declare_parameter('yolo_conf', 0.13)
        self.declare_parameter('yolo_iou', 0.50)
        self.declare_parameter('yolo_imgsz', 640)
        self.declare_parameter('yolo_device', '')
        self.declare_parameter('yolo_preprocess', True)
        self.declare_parameter('yolo_multi_pass', True)
        self.declare_parameter('yolo_warp_board', True)
        self.declare_parameter('yolo_enabled', False)
        self.declare_parameter('warp_board_size', 960)
        self.declare_parameter('heuristic_fallback', True)
        self.declare_parameter('board_flip_files', True)
        self.declare_parameter('depth_occupancy_enabled', True)
        self.declare_parameter('empty_depth_reference_path', '')
        self.declare_parameter('depth_occupancy_threshold_mm', 4.0)
        self.declare_parameter('depth_occupancy_min_conf', 0.30)
        self.declare_parameter(
            'board_manual_corners',
            [0, 0, 0, 0, 0, 0, 0, 0],
            ParameterDescriptor(type=ParameterType.PARAMETER_INTEGER_ARRAY),
        )
        self.declare_parameter('publish_debug_image', True)
        self.declare_parameter('debug_image_topic', 'vision/debug/top_view')
        self.declare_parameter('use_starting_occupancy_on_failure', False)
        self.declare_parameter('live_preview_enabled', True)
        self.declare_parameter('live_preview_rate_hz', 2.0)
        self.declare_parameter('publish_live_occupancy', True)

        self.scan_id = 0
        self._manual_corners_value = self._load_manual_corners()
        if self._manual_corners_value is None:
            self.get_logger().warn(
                'board_manual_corners not set — auto corner detect will fail with pieces on board. '
                'Run: ros2 run chess_board_detector calibrate_corners --image /path/to/frame.jpg'
            )
        self.bridge = CvBridge()
        self.board_detector = BoardDetector(
            flip_files=bool(self.get_parameter('board_flip_files').value),
        )
        self._empty_depth_reference, self._empty_depth_warp_size = self._load_depth_reference()
        self.piece_detector = ChessPieceDetector(
            model_path=self.get_parameter('yolo_model_path').value,
            conf=float(self.get_parameter('yolo_conf').value),
            iou=float(self.get_parameter('yolo_iou').value),
            imgsz=int(self.get_parameter('yolo_imgsz').value),
            device=self.get_parameter('yolo_device').value,
        )
        self.piece_detector.set_preprocess(bool(self.get_parameter('yolo_preprocess').value))
        self.piece_detector.set_multi_pass(bool(self.get_parameter('yolo_multi_pass').value))
        self.camera = create_camera_buffer(
            self,
            source=self.get_parameter('camera_source').value,
            topic=self.get_parameter('camera_topic').value,
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

        self.live_pub = None
        if self.get_parameter('publish_live_occupancy').value:
            self.live_pub = self.create_publisher(BoardState, 'vision/live_occupancy', 10)

        if self.get_parameter('depth_occupancy_enabled').value:
            if self._empty_depth_reference is None:
                self.get_logger().warn(
                    'depth_occupancy_enabled but empty_depth_reference_path not loaded — '
                    'run: ros2 run chess_occupancy calibrate_empty_depth --output /path/empty_board_depth.npz '
                    '--corners ...'
                )
            else:
                self.get_logger().info(
                    f'depth occupancy reference loaded '
                    f'(warp_size={self._empty_depth_warp_size})'
                )

        self.srv = self.create_service(ScanBoard, 'vision/scan_board', self.handle_scan)
        self.get_logger().info('Occupancy scan service ready on vision/scan_board')

        if self.get_parameter('live_preview_enabled').value and (
            self.debug_pub is not None or self.live_pub is not None
        ):
            rate = max(float(self.get_parameter('live_preview_rate_hz').value), 0.2)
            self.create_timer(1.0 / rate, self._on_live_preview)
            self.get_logger().info(
                f'Live preview enabled ({rate:.1f} Hz) on '
                f'{self.get_parameter("debug_image_topic").value}'
            )

    def _load_depth_reference(self) -> tuple[np.ndarray | None, int | None]:
        path = str(self.get_parameter('empty_depth_reference_path').value).strip()
        if not path:
            return None, None
        loaded = load_empty_depth_reference(path)
        if loaded is None:
            self.get_logger().warn(f'failed to load empty depth reference: {path}')
            return None, None
        cell_medians, warp_size = loaded
        configured_warp = int(self.get_parameter('warp_board_size').value)
        if warp_size != configured_warp:
            self.get_logger().warn(
                f'empty depth warp_size={warp_size} != warp_board_size={configured_warp}'
            )
        return cell_medians, warp_size

    def _load_manual_corners(self) -> list[float] | None:
        try:
            manual_corners = [float(v) for v in self.get_parameter('board_manual_corners').value]
        except (ParameterUninitializedException, TypeError, ValueError):
            return None
        return manual_corners if len(manual_corners) == 8 and any(v != 0 for v in manual_corners) else None

    def _manual_corners(self) -> list[float] | None:
        return self._manual_corners_value

    def _draw_occupancy_cells(self, image, cells: list[bool]):
        import cv2

        if self.board_detector.board_to_image is None:
            return image

        overlay = image.copy()
        for row in range(8):
            for col in range(8):
                if not cells[row * 8 + col]:
                    continue
                center_board = np.array([[[col + 0.5, row + 0.5]]], dtype=np.float32)
                center_img = cv2.perspectiveTransform(
                    center_board,
                    self.board_detector.board_to_image,
                )[0][0]
                cx, cy = int(center_img[0]), int(center_img[1])
                cv2.circle(overlay, (cx, cy), 14, (0, 200, 255), 2)
        return cv2.addWeighted(overlay, 0.55, image, 0.45, 0)

    def _compose_debug_image(self, frame, scan_result):
        import cv2

        debug_image = frame.copy()
        if self.board_detector.is_calibrated:
            debug_image = self.board_detector.draw_board_roi(debug_image)
        if scan_result.board_detected:
            debug_image = self.board_detector.draw_board_grid(debug_image)
            debug_image = self._draw_occupancy_cells(debug_image, scan_result.cells)
            occupied = sum(scan_result.cells)
            cv2.putText(
                debug_image,
                f'occupied={occupied}/64 | {scan_result.message}',
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            if scan_result.depth_debug is not None:
                debug_image = self._add_warped_inset(
                    debug_image,
                    scan_result.depth_debug,
                    label='depth diff',
                    anchor='br',
                )
        else:
            cv2.putText(
                debug_image,
                f'board not found: {scan_result.message}',
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
        return debug_image

    def _add_warped_inset(
        self,
        image: np.ndarray,
        warped: np.ndarray,
        *,
        label: str = 'warped',
        anchor: str = 'bl',
    ) -> np.ndarray:
        import cv2

        h, w = image.shape[:2]
        inset_w = min(240, w // 4)
        inset_h = inset_w
        small = cv2.resize(warped, (inset_w, inset_h), interpolation=cv2.INTER_AREA)
        x0 = 12 if anchor == 'bl' else max(12, w - inset_w - 12)
        y0 = max(40, h - inset_h - 12)
        roi = image[y0 : y0 + inset_h, x0 : x0 + inset_w]
        if roi.shape[:2] != small.shape[:2]:
            return image
        image[y0 : y0 + inset_h, x0 : x0 + inset_w] = small
        cv2.rectangle(image, (x0, y0), (x0 + inset_w, y0 + inset_h), (0, 255, 255), 2)
        cv2.putText(
            image,
            label,
            (x0, y0 - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return image

    def _build_debug_image(self, frame, scan_result):
        return self._compose_debug_image(frame, scan_result)

    def _scan_options(self) -> dict:
        return {
            'warp_board': bool(self.get_parameter('yolo_warp_board').value),
            'warp_size': int(self.get_parameter('warp_board_size').value),
            'heuristic_fallback': bool(self.get_parameter('heuristic_fallback').value),
            'depth_occupancy_enabled': bool(self.get_parameter('depth_occupancy_enabled').value),
            'empty_depth_reference': self._empty_depth_reference,
            'depth_threshold_mm': float(self.get_parameter('depth_occupancy_threshold_mm').value),
            'depth_min_conf': float(self.get_parameter('depth_occupancy_min_conf').value),
            'yolo_enabled': bool(self.get_parameter('yolo_enabled').value),
        }

    def _capture_frames(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        settling = int(self.get_parameter('settling_time_ms').value)
        stable = int(self.get_parameter('stable_frame_count').value)
        if hasattr(self.camera, 'wait_for_stable_color_depth'):
            return self.camera.wait_for_stable_color_depth(stable, settling)
        frame = self.camera.wait_for_stable_frames(stable, settling)
        return frame, None

    def _run_scan(self, frame, depth_frame=None):
        return scan_board(
            frame,
            self.board_detector,
            self.piece_detector,
            self._manual_corners(),
            depth_image=depth_frame,
            **self._scan_options(),
        )

    def _on_live_preview(self) -> None:
        try:
            frame = self.camera.get_frame()
            if frame is None:
                return
            depth_frame = self.camera.get_depth_frame() if hasattr(self.camera, 'get_depth_frame') else None

            scan_result = self._run_scan(frame, depth_frame)
            if self.live_pub is not None and scan_result.board_detected:
                board_state = self._make_board_state(
                    list(scan_result.cells),
                    list(scan_result.confidence),
                    True,
                    scan_result.message,
                )
                self.live_pub.publish(board_state)

            if self.debug_pub is None:
                return
            debug_image = self._build_debug_image(frame, scan_result)
            self.debug_pub.publish(self.bridge.cv2_to_imgmsg(debug_image, encoding='bgr8'))
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'live preview failed: {exc}', throttle_duration_sec=5.0)

    def handle_scan(self, request, response):
        del request
        self.scan_id += 1

        frame, depth_frame = self._capture_frames()
        if frame is None:
            response.board_state = self._empty_board_state('camera frame unavailable')
            response.success = False
            response.message = 'camera frame unavailable'
            return response

        scan_result = self._run_scan(frame, depth_frame)

        if self.debug_pub is not None:
            debug_image = self._build_debug_image(frame, scan_result)
            self.debug_pub.publish(
                self.bridge.cv2_to_imgmsg(debug_image, encoding='bgr8')
            )

        if not scan_result.board_detected:
            if self.get_parameter('use_starting_occupancy_on_failure').value:
                cells = starting_occupancy()
                confidence = [0.0] * 64
                message = f'board not found, fallback occupancy: {scan_result.message}'
                valid = True
                success = True
            else:
                response.board_state = self._empty_board_state(scan_result.message)
                response.success = False
                response.message = scan_result.message
                return response
        else:
            cells = scan_result.cells
            confidence = scan_result.confidence
            message = scan_result.message
            valid = True
            success = True

        board_state = self._make_board_state(cells, confidence, valid, message)
        response.board_state = board_state
        response.success = success
        response.message = message
        return response

    def _make_board_state(
        self,
        cells: list[bool],
        confidence: list[float],
        valid: bool,
        message: str,
    ) -> BoardState:
        occupancy = BoardOccupancy()
        occupancy.header = Header()
        occupancy.header.stamp = self.get_clock().now().to_msg()
        occupancy.cells = cells
        occupancy.confidence = confidence

        board_state = BoardState()
        board_state.header = occupancy.header
        board_state.occupancy = occupancy
        board_state.scan_id = self.scan_id
        board_state.valid = valid
        board_state.message = message
        return board_state

    def _empty_board_state(self, message: str) -> BoardState:
        return self._make_board_state(
            [False] * 64,
            [0.0] * 64,
            False,
            message,
        )

    def destroy_node(self) -> bool:
        self.camera.destroy()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = OccupancyNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
