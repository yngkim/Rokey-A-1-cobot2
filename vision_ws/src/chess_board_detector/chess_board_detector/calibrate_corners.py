#!/usr/bin/env python3
"""Click four board corners on an image and print board_manual_corners YAML."""

from __future__ import annotations

import argparse
import sys

import cv2

from chess_board_detector.board_detector import BoardDetector


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Calibrate board_manual_corners by clicking TL,TR,BR,BL')
    parser.add_argument('--image', required=True, help='Path to camera frame (1280x720 recommended)')
    parser.add_argument(
        '--flip-files',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Mirror a-h file mapping (default: true, matches occupancy_node)',
    )
    args = parser.parse_args(argv)

    image = cv2.imread(args.image)
    if image is None:
        print(f'failed to read image: {args.image}', file=sys.stderr)
        return 1

    clicks: list[tuple[int, int]] = []
    labels = ['TL', 'TR', 'BR', 'BL']

    def on_mouse(event, x, y, _flags, _param) -> None:
        if event != cv2.EVENT_LBUTTONDOWN or len(clicks) >= 4:
            return
        clicks.append((x, y))
        print(f'{labels[len(clicks) - 1]}: ({x}, {y})')

    window = 'calibrate_corners (TL, TR, BR, BL)'
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)

    while True:
        display = image.copy()
        for idx, (x, y) in enumerate(clicks):
            cv2.circle(display, (x, y), 6, (0, 255, 255), -1)
            cv2.putText(
                display,
                labels[idx],
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
                cv2.line(display, pts[i], pts[i + 1], (0, 255, 0), 2)
            detector = BoardDetector(flip_files=args.flip_files)
            result = detector.detect_corners(image, [float(v) for pt in clicks for v in pt])
            if result.success:
                display = detector.draw_board_roi(display)
                display = detector.draw_board_grid(display)
        hint = f'click {labels[len(clicks)]}' if len(clicks) < 4 else 'ENTER=save, r=reset, ESC=quit'
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
    flat = [coord for point in clicks for coord in point]
    print('\nboard_manual_corners: [' + ', '.join(str(v) for v in flat) + ']')
    print(f'board_flip_files: {str(args.flip_files).lower()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
