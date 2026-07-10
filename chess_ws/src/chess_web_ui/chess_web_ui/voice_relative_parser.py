"""Relative voice commands like 'a2 pawn one square forward'."""

from __future__ import annotations

import re

import chess

from chess_web_ui.voice_move_parser import (
    VoiceMoveParseError,
    VoiceMoveParseOk,
    VoiceMoveParsed,
    VoiceMoveParseResult,
    normalize_transcript,
)

_RELATIVE_FORWARD = re.compile(
    r'\b([a-h])\s*([1-8])\b'
    r'(?:\s*(?:의)?\s*(?:폰|말|나이트|비숍|룩|퀸|킹|pawn|knight|bishop|rook|queen|king))?'
    r'(?:\s*(?:을|를))?'
    r'\s*(?:(?:한|1|하나)\s*칸|(?:두|2|둘)\s*칸|(?:세|3)\s*칸)?\s*'
    r'(?:전진|앞|앞으로|forward)',
    re.IGNORECASE,
)

_COMPACT_FORWARD = re.compile(
    r'([a-h])([1-8])'
    r'(?:의)?(?:폰|말)?'
    r'(?:(?:한|1)칸|(?:두|2)칸|(?:세|3)칸)?'
    r'(?:전진|앞)',
    re.IGNORECASE,
)

_RELATIVE_SIDE = re.compile(
    r'\b([a-h])\s*([1-8])\b'
    r'(?:\s*(?:의)?\s*폰)?'
    r'(?:\s*(?:을|를))?'
    r'\s*(?:(?:한|1)\s*칸\s*)?'
    r'(왼쪽|왼|오른쪽|오른|left|right)'
    r'(?!\s*(?:대각|대각선|diagonal))',
    re.IGNORECASE,
)

_RELATIVE_DIAGONAL = re.compile(
    r'\b([a-h])\s*([1-8])\b'
    r'(?:\s*(?:의)?\s*폰)?'
    r'(?:\s*(?:을|를))?'
    r'\s*(?:(?:한|1)\s*칸\s*)?'
    r'(왼쪽|왼|오른쪽|오른|left|right)?'
    r'\s*(?:대각|대각선|diagonal)',
    re.IGNORECASE,
)


def _human_is_white(human_color: str) -> bool:
    return human_color.strip().lower() != 'black'


def _forward_delta(human_color: str, *, squares: int) -> int:
    return squares if _human_is_white(human_color) else -squares


def _side_delta(direction: str) -> int:
    token = direction.strip().lower()
    if token.startswith('왼') or token == 'left':
        return -1
    return 1


def _pawn_forward_to(from_sq: str, *, squares: int, human_color: str) -> str | None:
    file_ch = from_sq[0]
    rank = int(from_sq[1])
    target_rank = rank + _forward_delta(human_color, squares=squares)
    if not (1 <= target_rank <= 8):
        return None
    return f'{file_ch}{target_rank}'


def _offset_to(from_sq: str, *, file_delta: int, rank_delta: int) -> str | None:
    file_idx = ord(from_sq[0]) - ord('a') + file_delta
    rank = int(from_sq[1]) + rank_delta
    if not (0 <= file_idx <= 7 and 1 <= rank <= 8):
        return None
    return f'{chr(ord("a") + file_idx)}{rank}'


def _is_human_pawn(fen: str, from_sq: str, human_color: str) -> bool:
    board = chess.Board(fen)
    try:
        square = chess.parse_square(from_sq)
    except ValueError:
        return False
    piece = board.piece_at(square)
    if piece is None or piece.piece_type != chess.PAWN:
        return False
    human_is_white = _human_is_white(human_color)
    return piece.color == chess.WHITE if human_is_white else piece.color == chess.BLACK


def _steps_from_match(match: re.Match[str]) -> int:
    matched_text = match.group(0)
    if re.search(r'(?:세|3)\s*칸|3칸', matched_text):
        return 3
    if re.search(r'(?:두|2|둘)\s*칸|두칸|2칸', matched_text):
        return 2
    return 1


def _try_forward(
    transcript: str,
    fen: str,
    human_color: str,
) -> VoiceMoveParseResult:
    text = normalize_transcript(transcript)
    compact = re.sub(r'\s+', '', text)
    match = _COMPACT_FORWARD.search(compact) or _RELATIVE_FORWARD.search(text)
    if match is None:
        return VoiceMoveParseError(kind='parse_error', message='no forward pattern')

    from_sq = f'{match.group(1).lower()}{match.group(2)}'
    squares = _steps_from_match(match)
    if not _is_human_pawn(fen, from_sq, human_color):
        return VoiceMoveParseError(kind='parse_error', message=f'{from_sq} is not your pawn')

    to_sq = _pawn_forward_to(from_sq, squares=squares, human_color=human_color)
    if to_sq is None:
        return VoiceMoveParseError(kind='parse_error', message='forward move off board')
    return VoiceMoveParseOk(VoiceMoveParsed(from_sq=from_sq, to_sq=to_sq))


def _try_side(
    transcript: str,
    fen: str,
    human_color: str,
) -> VoiceMoveParseResult:
    text = normalize_transcript(transcript)
    match = _RELATIVE_SIDE.search(text)
    if match is None:
        return VoiceMoveParseError(kind='parse_error', message='no side pattern')

    from_sq = f'{match.group(1).lower()}{match.group(2)}'
    if not _is_human_pawn(fen, from_sq, human_color):
        return VoiceMoveParseError(kind='parse_error', message=f'{from_sq} is not your pawn')

    file_delta = _side_delta(match.group(3))
    rank_delta = _forward_delta(human_color, squares=1)
    to_sq = _offset_to(from_sq, file_delta=file_delta, rank_delta=rank_delta)
    if to_sq is None:
        return VoiceMoveParseError(kind='parse_error', message='side move off board')
    return VoiceMoveParseOk(VoiceMoveParsed(from_sq=from_sq, to_sq=to_sq))


def _try_diagonal(
    transcript: str,
    fen: str,
    human_color: str,
) -> VoiceMoveParseResult:
    text = normalize_transcript(transcript)
    match = _RELATIVE_DIAGONAL.search(text)
    if match is None:
        return VoiceMoveParseError(kind='parse_error', message='no diagonal pattern')

    from_sq = f'{match.group(1).lower()}{match.group(2)}'
    if not _is_human_pawn(fen, from_sq, human_color):
        return VoiceMoveParseError(kind='parse_error', message=f'{from_sq} is not your pawn')

    direction = match.group(3) or '왼쪽'
    file_delta = _side_delta(direction)
    rank_delta = _forward_delta(human_color, squares=1)
    to_sq = _offset_to(from_sq, file_delta=file_delta, rank_delta=rank_delta)
    if to_sq is None:
        return VoiceMoveParseError(kind='parse_error', message='diagonal move off board')
    return VoiceMoveParseOk(VoiceMoveParsed(from_sq=from_sq, to_sq=to_sq))


def parse_relative_voice_move(
    transcript: str,
    fen: str,
    human_color: str,
) -> VoiceMoveParseResult:
    for parser in (_try_forward, _try_side, _try_diagonal):
        result = parser(transcript, fen, human_color)
        if isinstance(result, VoiceMoveParseOk):
            return result
    return VoiceMoveParseError(kind='parse_error', message='no relative move pattern')
