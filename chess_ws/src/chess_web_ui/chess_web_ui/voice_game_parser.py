"""Parse non-move game voice commands (confirm, undo, restore, resign)."""

from __future__ import annotations

import re
from typing import Literal

from chess_web_ui.voice_stt_normalize import preprocess_transcript

GameVoiceAction = Literal['confirm', 'undo', 'restore', 'resign']

_SQUARE_RE = re.compile(r'[a-h][1-8]', re.IGNORECASE)
_MOVE_HINT_RE = re.compile(
    r'(?:잡|잡아|이동|옮|앞|왼|오른|대각|폰|나이트|비숍|룩|퀸|킹|knight|bishop|rook|queen|king|pawn)',
    re.IGNORECASE,
)

_CONFIRM_RE = re.compile(
    r'(?:수\s*(?:두었|뒀|놨)|확인(?:해|했|됐)?|움직였|맞아|맞습니다|맞아요|뒀어|놨어|player\s*moved)',
    re.IGNORECASE,
)
_UNDO_RE = re.compile(
    r'(?:한\s*턴\s*전|되돌|취소|undo|이전\s*수)',
    re.IGNORECASE,
)
_RESTORE_RE = re.compile(
    r'(?:보드\s*정리|복구|정리해|맞춰|restore)',
    re.IGNORECASE,
)
_RESIGN_RE = re.compile(
    r'(?:기권|포기|항복|resign)',
    re.IGNORECASE,
)


def _normalized(transcript: str) -> str:
    return preprocess_transcript(transcript).strip().lower()


def _looks_like_move_command(text: str) -> bool:
    if _SQUARE_RE.search(text):
        return True
    return bool(_MOVE_HINT_RE.search(text))


def parse_game_voice_command(transcript: str) -> GameVoiceAction | None:
    """Return a game action if transcript is a short game command, else None."""
    text = _normalized(transcript)
    if not text:
        return None
    if _looks_like_move_command(text):
        return None

    if _RESIGN_RE.search(text):
        return 'resign'
    if _UNDO_RE.search(text):
        return 'undo'
    if _RESTORE_RE.search(text):
        return 'restore'
    if _CONFIRM_RE.search(text):
        return 'confirm'
    return None
