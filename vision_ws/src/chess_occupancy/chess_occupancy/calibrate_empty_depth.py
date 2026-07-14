#!/usr/bin/env python3
"""Capture an empty-board depth reference for depth-based occupancy."""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy

from chess_board_detector.board_detector import BoardDetector
from chess_occupancy.depth_reference import cell_medians_from_warped_depth, save_empty_depth_reference
from chess_piece_classifier.realsense import ImgNode


def _default_params_path() -> str:
    try:
        from ament_index_python.packages import get_package_share_directory

        share = get_package_share_directory('chess_vision_bringup')
        return str(Path(share) / 'config' / 'vision_realsense_params.yaml')
    except Exception:  # noqa: BLE001
        # __file__ = .../vision_ws/src/chess_occupancy/chess_occupancy/this_file.py
        # parents[2] = .../vision_ws/src
        return str(
            Path(__file__).resolve().parents[2]
            / 'chess_vision_bringup' / 'config' / 'vision_realsense_params.yaml'
        )


def _load_params_from_yaml(path: str) -> dict:
    text = Path(path).read_text(encoding='utf-8')
    params: dict = {}

    corner_match = re.search(r'board_manual_corners:\s*\[([^\]]+)\]', text)
    if corner_match:
        params['corners'] = [float(x) for x in corner_match.group(1).split(',')]

    for key, cast in (
        ('warp_board_size', int),
        ('settling_time_ms', int),
        ('stable_frame_count', int),
    ):
        match = re.search(rf'{key}:\s*(\S+)', text)
        if match:
            params[key] = cast(match.group(1))

    flip_match = re.search(r'board_flip_files:\s*(true|false)', text, re.IGNORECASE)
    if flip_match:
        params['board_flip_files'] = flip_match.group(1).lower() == 'true'

    return params

def _wait_for_stable_frames(
    img_node: ImgNode,
    frame_count: int,
    settling_ms: int,
    wait_timeout_sec: float = 20.0,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    if settling_ms > 0:
        time.sleep(settling_ms / 1000.0)

    print(
        'waiting for RealSense color + aligned depth '
        '(vision_manual must be running)...',
        flush=True,
    )
    deadline = time.time() + wait_timeout_sec
    while time.time() < deadline:
        rclpy.spin_once(img_node, timeout_sec=0.05)
        has_color = img_node.get_color_frame() is not None
        has_depth = img_node.get_depth_frame() is not None
        if has_color and has_depth:
            break
        if int(time.time()) % 3 == 0:
            missing = []
            if not has_color:
                missing.append('color')
            if not has_depth:
                missing.append('depth')
            print(f'  still waiting for: {", ".join(missing)}', flush=True)
            time.sleep(0.2)
    else:
        return None, None

    print('frames received, stabilizing...', flush=True)
    last_color = None
    stable = 0
    deadline = time.time() + 10.0
    while stable < frame_count and time.time() < deadline:
        rclpy.spin_once(img_node, timeout_sec=0.05)
        color = img_node.get_color_frame()
        depth = img_node.get_depth_frame()
        if color is None or depth is None:
            continue
        if last_color is not None and color.shape == last_color.shape:
            diff = float(np.mean(cv2.absdiff(color, last_color)))
            if diff < 2.0:
                stable += 1
            else:
                stable = 0
        last_color = color
        time.sleep(0.05)

    if last_color is None:
        return None, None
    rclpy.spin_once(img_node, timeout_sec=0.05)
    return img_node.get_color_frame(), img_node.get_depth_frame()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Save empty-board depth reference (.npz) for depth occupancy',
    )
    parser.add_argument('--output', required=True, help='Output .npz path')
    parser.add_argument(
        '--params-file',
        default='',
        help='vision_realsense_params.yaml (loads board_manual_corners by default)',
    )
    parser.add_argument('--warp-size', type=int, default=0)
    parser.add_argument('--settling-ms', type=int, default=0)
    parser.add_argument('--stable-frames', type=int, default=0)
    parser.add_argument(
        '--corners',
        nargs=8,
        type=float,
        help='board_manual_corners: x0 y0 x1 y1 x2 y2 x3 y3 (TL TR BR BL)',
    )
    parser.add_argument(
        '--flip-files',
        action=argparse.BooleanOptionalAction,
        default=None,
        help='Mirror a-h file mapping (default: from params file)',
    )
    args = parser.parse_args(argv)

    params_path = args.params_file.strip() or _default_params_path()
    file_params = _load_params_from_yaml(params_path) if Path(params_path).is_file() else {}

    corners = list(args.corners) if args.corners is not None else file_params.get('corners')
    if not corners or len(corners) != 8:
        print(
            'ERROR: board corners required. Either:\n'
            f'  --params-file {params_path}\n'
            '  or --corners x0 y0 x1 y1 x2 y2 x3 y3',
            file=sys.stderr,
        )
        return 1

    warp_size = args.warp_size or int(file_params.get('warp_board_size', 960))
    settling_ms = args.settling_ms or int(file_params.get('settling_time_ms', 500))
    stable_frames = args.stable_frames or int(file_params.get('stable_frame_count', 5))
    flip_files = args.flip_files
    if flip_files is None:
        flip_files = bool(file_params.get('board_flip_files', True))

    print(f'params: {params_path}', flush=True)
    print(f'corners: {corners}', flush=True)
    rclpy.init()
    img_node = ImgNode()
    try:
        color, depth = _wait_for_stable_frames(img_node, stable_frames, settling_ms)
        if color is None or depth is None:
            print(
                'ERROR: failed to receive color/depth from RealSense within timeout.\n'
                '  1) Start vision_manual first: ros2 launch chess_web_ui vision_manual.launch.py use_fake:=false\n'
                '  2) Wait until camera preview works in the web UI\n'
                '  3) Remove all pieces from the board, then re-run this command\n'
                '  4) Check topics: ros2 topic hz /camera/camera/aligned_depth_to_color/image_raw',
                file=sys.stderr,
            )
            return 1

        detector = BoardDetector(flip_files=flip_files)
        result = detector.detect_corners(color, corners)
        if not result.success:
            print(f'ERROR: board calibration failed: {result.message}', file=sys.stderr)
            return 1

        warped_depth = detector.warp_to_board(depth, warp_size, interpolation=cv2.INTER_NEAREST)
        cell_medians = cell_medians_from_warped_depth(warped_depth, warp_size)
        if np.isnan(cell_medians).sum() > 32:
            print(
                'ERROR: too many invalid depth cells — check lighting and empty board',
                file=sys.stderr,
            )
            return 1

        save_empty_depth_reference(args.output, cell_medians, warp_size)
        valid = int(np.sum(~np.isnan(cell_medians)))
        print(f'saved empty depth reference: {args.output}')
        print(f'warp_size: {warp_size}, valid_cells: {valid}/64')
        print('median depth mm (row 0 = rank 1):')
        for row in range(8):
            vals = ' '.join(
                f'{cell_medians[row, col]:6.0f}' if not np.isnan(cell_medians[row, col]) else '   nan'
                for col in range(8)
            )
            print(f'  rank {row + 1}: {vals}')
        return 0
    finally:
        img_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
