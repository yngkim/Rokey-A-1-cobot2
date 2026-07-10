#!/usr/bin/env python3
"""Click four side-view board corners (a1, h1, h8, a8) and save calibration JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

LABELS = ['a1', 'h1', 'h8', 'a8']


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Calibrate side-view board_corners by clicking a1, h1, h8, a8',
    )
    parser.add_argument('--image', required=True, help='Path to side camera frame')
    parser.add_argument('--output', required=True, help='Path to board_twin_side_calibration.json')
    parser.add_argument('--webcam-device', type=int, default=10)
    parser.add_argument(
        '--flip-files',
        action=argparse.BooleanOptionalAction,
        default=False,
        help='Mirror a-h file mapping',
    )
    parser.add_argument(
        '--board-flipped',
        action=argparse.BooleanOptionalAction,
        default=False,
        help='Rotate board 180 degrees in mapping',
    )
    args = parser.parse_args(argv)

    image = cv2.imread(args.image)
    if image is None:
        print(f'failed to read image: {args.image}', file=sys.stderr)
        return 1

    clicks: list[tuple[int, int]] = []

    def on_mouse(event, x, y, _flags, _param) -> None:
        if event != cv2.EVENT_LBUTTONDOWN or len(clicks) >= 4:
            return
        clicks.append((x, y))
        print(f'{LABELS[len(clicks) - 1]}: ({x}, {y})')

    window = 'calibrate_side_corners (a1, h1, h8, a8)'
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)

    while True:
        display = image.copy()
        for idx, (x, y) in enumerate(clicks):
            cv2.circle(display, (x, y), 6, (0, 255, 255), -1)
            cv2.putText(
                display,
                LABELS[idx],
                (x + 8, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
        if len(clicks) == 4:
            pts = clicks + [clicks[0]]
            for i in range(4):
                cv2.line(display, pts[i], pts[i + 1], (0, 200, 255), 2)
        hint = (
            f'click {LABELS[len(clicks)]}'
            if len(clicks) < 4
            else 'ENTER=save, r=reset, ESC=quit'
        )
        cv2.putText(display, hint, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow(window, display)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10) and len(clicks) == 4:
            break
        if key == ord('r'):
            clicks.clear()
        if key == 27:
            return 1

    cv2.destroyAllWindows()
    height, width = image.shape[:2]
    payload = {
        'board_corners': [float(v) for pt in clicks for v in pt],
        'flip_files': bool(args.flip_files),
        'board_flipped': bool(args.board_flipped),
        'webcam_device': int(args.webcam_device),
        'camera_width': int(width),
        'camera_height': int(height),
        '_comment': 'Order: a1, h1, h8, a8 image coordinates.',
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    print(f'saved {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
