"""Empty-board depth reference storage and per-cell median helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def cell_medians_from_warped_depth(
    warped_depth: np.ndarray,
    warp_size: int,
    margin_ratio: float = 0.22,
    percentile: float = 50.0,
    min_valid_pixels: int = 4,
) -> np.ndarray:
    """Return 8x8 depth statistic (mm) per cell; NaN where too few valid pixels."""
    cell_px = warp_size / 8.0
    medians = np.full((8, 8), np.nan, dtype=np.float32)

    for row in range(8):
        for col in range(8):
            x1 = int(col * cell_px + cell_px * margin_ratio)
            y1 = int(row * cell_px + cell_px * margin_ratio)
            x2 = int((col + 1) * cell_px - cell_px * margin_ratio)
            y2 = int((row + 1) * cell_px - cell_px * margin_ratio)
            patch = warped_depth[y1:y2, x1:x2]
            if patch.size == 0:
                continue
            valid = patch.astype(np.float32)
            valid = valid[valid > 0.0]
            if valid.size < min_valid_pixels:
                continue
            if percentile <= 0.0:
                medians[row, col] = float(np.min(valid))
            elif percentile >= 100.0:
                medians[row, col] = float(np.max(valid))
            else:
                medians[row, col] = float(np.percentile(valid, percentile))

    return medians


def save_empty_depth_reference(path: str, cell_medians: np.ndarray, warp_size: int) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        cell_medians=np.asarray(cell_medians, dtype=np.float32),
        warp_size=int(warp_size),
    )


def load_empty_depth_reference(path: str) -> tuple[np.ndarray, int] | None:
    if not path:
        return None
    ref_path = Path(path)
    if not ref_path.is_file():
        return None
    data = np.load(ref_path)
    cell_medians = np.asarray(data['cell_medians'], dtype=np.float32)
    if cell_medians.shape != (8, 8):
        return None
    return cell_medians, int(data['warp_size'])
