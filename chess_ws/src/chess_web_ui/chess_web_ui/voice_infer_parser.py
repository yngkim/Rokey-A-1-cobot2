"""FEN-based inference for underspecified voice commands."""

from __future__ import annotations

import re

import chess

from chess_web_ui.voice_move_parser import (
    VoiceMoveParseError,
    VoiceMoveParseOk,
    VoiceMoveParsed,
    VoiceMoveParseResult,
    normalize_transcript,
    preprocess_transcript,
)

from chess_web_ui.voice_semantic_parser import should_skip_infer

_DIRECTION_HINT_RE = re.compile(
    r'(?:앞|뒤|왼|오른|대각|전진|forward|left|right|diagonal)',
    re.IGNORECASE,
)

_SQUARE_RE = re.compile(r'\b([a-h])([1-8])\b', re.IGNORECASE)
_DESTINATION_RE = re.compile(
    r'\b([a-h])([1-8])\b'
    r'(?:\s*(?:으로|로|까지|에))?',
    re.IGNORECASE,
)


def _human_is_white(human_color: str) -> bool:
    return human_color.strip().lower() != 'black'


def _human_legal_moves(fen: str, human_color: str) -> list[chess.Move]:
    board = chess.Board(fen)
    human_is_white = _human_is_white(human_color)
    if board.turn != (chess.WHITE if human_is_white else chess.BLACK):
        return []
    return list(board.legal_moves)


def _move_to_parsed(move: chess.Move) -> VoiceMoveParsed:
    promo = ''
    if move.promotion:
        promo = chess.piece_symbol(move.promotion)
    return VoiceMoveParsed(
        from_sq=chess.square_name(move.from_square),
        to_sq=chess.square_name(move.to_square),
        promotion=promo,
    )


def _extract_squares(text: str) -> list[str]:
    return [f'{match.group(1).lower()}{match.group(2)}' for match in _SQUARE_RE.finditer(text)]


def infer_destination_move(
    transcript: str,
    fen: str,
    human_color: str,
) -> VoiceMoveParseResult:
    """Resolve when only destination is given: 'e4로', 'e4 가'."""
    if _DIRECTION_HINT_RE.search(transcript):
        return VoiceMoveParseError(kind='parse_error', message='destination-only not applicable')
    if should_skip_infer(transcript):
        return VoiceMoveParseError(kind='parse_error', message='destination infer skipped for capture')
    raw = preprocess_transcript(transcript)
    text = normalize_transcript(raw or transcript)
    squares = _extract_squares(text)
    if len(squares) != 1:
        return VoiceMoveParseError(kind='parse_error', message='need single destination')

    to_sq = squares[0]
    try:
        to_square = chess.parse_square(to_sq)
    except ValueError:
        return VoiceMoveParseError(kind='parse_error', message='invalid destination')

    candidates = [
        move
        for move in _human_legal_moves(fen, human_color)
        if move.to_square == to_square
    ]
    if len(candidates) == 1:
        return VoiceMoveParseOk(_move_to_parsed(candidates[0]))
    if not candidates:
        return VoiceMoveParseError(kind='parse_error', message='no legal move to square')
    return VoiceMoveParseError(kind='ambiguous', message='multiple moves to square')


def infer_square_pair_move(
    transcript: str,
    fen: str,
    human_color: str,
) -> VoiceMoveParseResult:
    """Extract any two squares from messy transcript before strict token parsing."""
    raw = preprocess_transcript(transcript)
    squares = _extract_squares(normalize_transcript(raw or transcript))
    if len(squares) < 2:
        return VoiceMoveParseError(kind='parse_error', message='need two squares')

    from_sq, to_sq = squares[0], squares[1]
    board = chess.Board(fen)
    try:
        from_square = chess.parse_square(from_sq)
        to_square = chess.parse_square(to_sq)
    except ValueError:
        return VoiceMoveParseError(kind='parse_error', message='invalid squares')

    candidates = [
        move
        for move in _human_legal_moves(fen, human_color)
        if move.from_square == from_square and move.to_square == to_square
    ]
    if len(candidates) == 1:
        return VoiceMoveParseOk(_move_to_parsed(candidates[0]))
    if not candidates:
        return VoiceMoveParseError(kind='parse_error', message='illegal square pair')
    return VoiceMoveParseError(kind='ambiguous', message='ambiguous square pair')


def infer_voice_move(
    transcript: str,
    fen: str,
    human_color: str,
) -> VoiceMoveParseResult:
    if should_skip_infer(transcript):
        return VoiceMoveParseError(kind='parse_error', message='infer skipped for semantic command')

    pair = infer_square_pair_move(transcript, fen, human_color)
    if isinstance(pair, VoiceMoveParseOk):
        return pair
    return infer_destination_move(transcript, fen, human_color)
