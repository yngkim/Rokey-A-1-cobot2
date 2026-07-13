"""Resolve monorepo paths regardless of install/symlink layout."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SIDE_MODEL_REL = Path('model/weights/chess_final_side1_best.pt')
# stage1 is only the generic/open pretrain (public hand images, never saw this
# rig's camera angle, lighting, or the robot gripper) — val mAP50 0.71,
# precision 0.75, recall 0.67 on its own val set. stage2 finetunes stage1's
# weights on a custom dataset captured from this actual setup and is
# dramatically more accurate here: mAP50 0.97, precision 0.94, recall 0.97.
# Deploying stage1 was the direct cause of persistent false-positive hand
# detections (e.g. the moving gripper/pieces mistaken for a hand).
DEFAULT_HAND_MODEL_REL = Path('hand_yolo26_project/runs_stage2_finetune/weights/best.pt')
HF_SIDE_MODEL_FALLBACK = 'yamero999/chess-piece-detection-yolo11n'


def find_repo_root() -> Path:
    env = os.environ.get('CHESS_REPO_ROOT', '').strip()
    if env:
        root = Path(env).expanduser().resolve()
        if root.is_dir():
            return root

    starts: list[Path] = [Path.cwd().resolve()]
    try:
        starts.append(Path(__file__).resolve())
    except NameError:
        pass

    seen: set[Path] = set()
    for start in starts:
        base = start if start.is_dir() else start.parent
        for parent in [base, *base.parents]:
            if parent in seen:
                continue
            seen.add(parent)
            if (parent / DEFAULT_SIDE_MODEL_REL).is_file():
                return parent
            if (parent / 'chess_project_env.sh').is_file():
                return parent

    raise FileNotFoundError(
        'chess monorepo root not found (set CHESS_REPO_ROOT or run from Rokey-A-1-cobot2)'
    )


def default_side_model_path() -> str:
    return str(find_repo_root() / DEFAULT_SIDE_MODEL_REL)


def default_hand_model_path() -> str:
    return str(find_repo_root() / DEFAULT_HAND_MODEL_REL)


def resolve_hand_model_path(configured: str) -> str:
    token = (configured or '').strip()
    if token:
        path = Path(token).expanduser()
        if path.is_file():
            return str(path.resolve())
    try:
        local = find_repo_root() / DEFAULT_HAND_MODEL_REL
        if local.is_file():
            return str(local)
    except FileNotFoundError:
        pass
    if token:
        return token
    raise FileNotFoundError(
        f'hand model not found: {DEFAULT_HAND_MODEL_REL} (set hand_model_path launch arg)'
    )


def resolve_side_model_path(configured: str) -> str:
    token = (configured or '').strip()
    if token:
        path = Path(token).expanduser()
        if path.is_file():
            return str(path.resolve())
    try:
        local = find_repo_root() / DEFAULT_SIDE_MODEL_REL
        if local.is_file():
            return str(local)
    except FileNotFoundError:
        pass
    if token and token not in ('', HF_SIDE_MODEL_FALLBACK):
        return token
    return HF_SIDE_MODEL_FALLBACK
