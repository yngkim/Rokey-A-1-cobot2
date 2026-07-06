"""Resolve local paths and Hugging Face model IDs to a YOLO weights file."""

from __future__ import annotations

import os


def resolve_model_path(model_path: str) -> str:
    if not model_path:
        raise ValueError('model_path is empty')

    if model_path.startswith('http://') or model_path.startswith('https://'):
        return model_path

    if os.path.isfile(model_path):
        return model_path

    if '/' in model_path and not os.path.isabs(model_path):
        return _resolve_huggingface_model(model_path)

    raise FileNotFoundError(f'YOLO model not found: {model_path}')


def _resolve_huggingface_model(repo_id: str) -> str:
    from huggingface_hub import hf_hub_download

    candidates = [
        'best.pt',
        'weights/best.pt',
        'model.pt',
        f'{repo_id.split("/")[-1]}.pt',
    ]
    errors: list[str] = []
    for filename in candidates:
        try:
            return hf_hub_download(repo_id=repo_id, filename=filename)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'{filename}: {exc}')

    return f'https://huggingface.co/{repo_id}/resolve/main/best.pt'
