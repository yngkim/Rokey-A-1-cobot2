"""Semantic intent parsing for natural-language chess voice commands."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

import chess

from chess_web_ui.voice_move_parser import (
    VoiceMoveParseError,
    VoiceMoveParseOk,
    VoiceMoveParsed,
    VoiceMoveParseResult,
)
from chess_web_ui.voice_stt_normalize import preprocess_transcript

ActionKind = Literal['capture', 'move']

PIECE_NAME_TO_TYPE: dict[str, int] = {
    'pawn': chess.PAWN,
    '폰': chess.PAWN,
    'knight': chess.KNIGHT,
    '나이트': chess.KNIGHT,
    '말': chess.KNIGHT,
    'bishop': chess.BISHOP,
    '비숍': chess.BISHOP,
    'rook': chess.ROOK,
    '룩': chess.ROOK,
    'queen': chess.QUEEN,
    '퀸': chess.QUEEN,
    'king': chess.KING,
    '킹': chess.KING,
}

PIECE_TYPE_NAMES: dict[int, str] = {
    chess.PAWN: 'pawn',
    chess.KNIGHT: 'knight',
    chess.BISHOP: 'bishop',
    chess.ROOK: 'rook',
    chess.QUEEN: 'queen',
    chess.KING: 'king',
}

_CAPTURE_RE = re.compile(
    r'(?:잡|잡아|잡기|캡처|capture|먹|먹어|먹기)',
    re.IGNORECASE,
)
_MOVE_RE = re.compile(
    r'(?:이동|옮|가|move)',
    re.IGNORECASE,
)
_PIECE_RE = re.compile(
    r'(?:'
    + '|'.join(re.escape(name) for name in sorted(PIECE_NAME_TO_TYPE, key=len, reverse=True))
    + r')',
    re.IGNORECASE,
)
_SQUARE_RE = re.compile(
    r'([a-h])\s*([1-8])(?=\s|$|[^0-9a-hA-H]|(?=[가-힣]))',
    re.IGNORECASE,
)
_MAJOR_PIECE_RE = re.compile(
    r'(?:나이트|비숍|룩|퀸|킹|knight|bishop|rook|queen|king)',
    re.IGNORECASE,
)
_MOVER_TARGET_CAPTURE_RE = re.compile(
    r'(나이트|비숍|룩|퀸|킹|말|knight|bishop|rook|queen|king|pawn|폰)'
    r'(?:으로|를|을|로)?\s*'
    r'(폰|나이트|비숍|룩|퀸|킹|말|pawn|knight|bishop|rook|queen|king)?'
    r'.*?(?:잡|캡처|capture|먹)',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VoiceIntentSlots:
    from_sq: str | None = None
    to_sq: str | None = None
    piece: int | None = None
    action: ActionKind | None = None
    target_piece: int | None = None


def has_semantic_intent(transcript: str) -> bool:
    text = preprocess_transcript(transcript).strip().lower()
    if not text:
        return False
    has_capture = bool(_CAPTURE_RE.search(text))
    has_piece = bool(_PIECE_RE.search(text))
    has_square = bool(_SQUARE_RE.search(text))
    if has_capture and (has_piece or has_square):
        return True
    if _MAJOR_PIECE_RE.search(text) and has_square:
        return True
    return bool(has_piece and has_capture)


def should_skip_infer(transcript: str) -> bool:
    text = preprocess_transcript(transcript).strip().lower()
    if not text:
        return False
    has_capture = bool(_CAPTURE_RE.search(text))
    has_piece = bool(_PIECE_RE.search(text))
    has_square = bool(_SQUARE_RE.search(text))
    if has_capture and (has_piece or has_square):
        return True
    return bool(_MAJOR_PIECE_RE.search(text) and has_capture)


def should_skip_relative(transcript: str) -> bool:
    return should_skip_infer(transcript)


def has_blocking_semantic_intent(transcript: str) -> bool:
    """Capture or explicit piece intent — block full-list LLM guessing."""
    text = preprocess_transcript(transcript).strip().lower()
    if not text:
        return False
    has_capture = bool(_CAPTURE_RE.search(text))
    has_piece = bool(_PIECE_RE.search(text))
    has_square = bool(_SQUARE_RE.search(text))
    if has_capture and (has_piece or has_square):
        return True
    if _MAJOR_PIECE_RE.search(text) and (has_capture or has_square):
        return True
    slots = extract_intent_slots(transcript)
    return slots.piece is not None or slots.action == 'capture'


def _human_is_white(human_color: str) -> bool:
    return human_color.strip().lower() != 'black'


def _human_legal_moves(fen: str, human_color: str) -> list[chess.Move]:
    board = chess.Board(fen)
    human_is_white = _human_is_white(human_color)
    if board.turn != (chess.WHITE if human_is_white else chess.BLACK):
        return []
    return list(board.legal_moves)


def _extract_squares(text: str) -> list[str]:
    return [
        f'{match.group(1).lower()}{match.group(2)}'
        for match in _SQUARE_RE.finditer(text)
    ]


def _find_all_piece_types(text: str) -> list[int]:
    found: list[int] = []
    for match in _PIECE_RE.finditer(text):
        piece_type = PIECE_NAME_TO_TYPE.get(match.group(0).lower())
        if piece_type is not None:
            found.append(piece_type)
    return found


def _pick_capture_from_square(
    text: str,
    squares: list[str],
    fen: str | None,
    human_color: str,
    piece: int | None,
) -> str | None:
    if not squares:
        return None
    if not fen or piece is None:
        return squares[0]

    board = chess.Board(fen)
    human_is_white = _human_is_white(human_color)
    human_color_flag = chess.WHITE if human_is_white else chess.BLACK

    matching: list[str] = []
    for sq_name in squares:
        try:
            sq = chess.parse_square(sq_name)
        except ValueError:
            continue
        board_piece = board.piece_at(sq)
        if (
            board_piece is not None
            and board_piece.color == human_color_flag
            and board_piece.piece_type == piece
        ):
            matching.append(sq_name)

    if len(matching) == 1:
        return matching[0]
    if matching:
        for sq_name in reversed(squares):
            if sq_name in matching:
                return sq_name

    for sq_name in reversed(squares):
        if re.search(
            rf'{re.escape(sq_name)}(?:의|에서)?\s*(?:'
            + '|'.join(
                re.escape(name)
                for name, ptype in PIECE_NAME_TO_TYPE.items()
                if ptype == piece
            )
            + r')',
            text,
            re.IGNORECASE,
        ):
            return sq_name

    return squares[0] if len(squares) == 1 else None


def _apply_board_piece_hint(
    slots: VoiceIntentSlots,
    fen: str | None,
    human_color: str,
) -> VoiceIntentSlots:
    if not fen or not slots.from_sq:
        return slots
    board = chess.Board(fen)
    try:
        from_square = chess.parse_square(slots.from_sq)
    except ValueError:
        return slots
    piece = board.piece_at(from_square)
    if piece is None:
        return slots
    human_is_white = _human_is_white(human_color)
    if piece.color != (chess.WHITE if human_is_white else chess.BLACK):
        return slots
    if slots.piece is None or slots.piece != piece.piece_type:
        return replace(slots, piece=piece.piece_type)
    return slots


def extract_intent_slots(
    transcript: str,
    fen: str | None = None,
    human_color: str = 'white',
) -> VoiceIntentSlots:
    raw = preprocess_transcript(transcript)
    text = (raw or transcript).strip().lower()

    squares = _extract_squares(text)
    from_sq = squares[0] if squares else None
    to_sq = squares[1] if len(squares) > 1 else None

    action: ActionKind | None = None
    if _CAPTURE_RE.search(text):
        action = 'capture'
    elif _MOVE_RE.search(text):
        action = 'move'

    piece_types = _find_all_piece_types(text)
    piece = piece_types[0] if piece_types else None
    target_piece = piece_types[1] if len(piece_types) > 1 else None

    capture_match = _MOVER_TARGET_CAPTURE_RE.search(text)
    if capture_match and action == 'capture':
        mover_type = PIECE_NAME_TO_TYPE.get(capture_match.group(1).lower())
        if mover_type is not None:
            piece = mover_type
        target_token = capture_match.group(2)
        if target_token:
            target_piece = PIECE_NAME_TO_TYPE.get(target_token.lower())
        from_sq = _pick_capture_from_square(text, squares, fen, human_color, piece)
        to_sq = None
    elif action == 'capture' and target_piece is None and piece is not None:
        for match in _PIECE_RE.finditer(text):
            token = match.group(0).lower()
            piece_type = PIECE_NAME_TO_TYPE.get(token)
            if piece_type is not None and piece_type != piece:
                target_piece = piece_type
                break

    slots = VoiceIntentSlots(
        from_sq=from_sq,
        to_sq=to_sq,
        piece=piece,
        action=action,
        target_piece=target_piece,
    )
    return _apply_board_piece_hint(slots, fen, human_color)


def filter_moves_by_intent(
    fen: str,
    human_color: str,
    slots: VoiceIntentSlots,
) -> list[chess.Move]:
    board = chess.Board(fen)
    candidates = list(_human_legal_moves(fen, human_color))

    if slots.from_sq:
        try:
            from_square = chess.parse_square(slots.from_sq)
        except ValueError:
            return []
        candidates = [move for move in candidates if move.from_square == from_square]

    if slots.to_sq:
        try:
            to_square = chess.parse_square(slots.to_sq)
        except ValueError:
            return []
        candidates = [move for move in candidates if move.to_square == to_square]

    if slots.piece is not None:
        candidates = [
            move
            for move in candidates
            if board.piece_at(move.from_square)
            and board.piece_at(move.from_square).piece_type == slots.piece
        ]

    if slots.action == 'capture':
        candidates = [move for move in candidates if board.is_capture(move)]

    if slots.target_piece is not None:
        filtered: list[chess.Move] = []
        for move in candidates:
            captured = board.piece_at(move.to_square)
            if captured is not None and captured.piece_type == slots.target_piece:
                filtered.append(move)
        candidates = filtered

    return candidates


def filter_moves_relaxed(
    fen: str,
    human_color: str,
    slots: VoiceIntentSlots,
) -> list[chess.Move]:
    """Looser filters when strict intent matching finds no unique move."""
    board = chess.Board(fen)
    base = list(_human_legal_moves(fen, human_color))
    if not base:
        return []

    stated_from = bool(slots.from_sq)

    if slots.from_sq and slots.action == 'capture':
        try:
            from_square = chess.parse_square(slots.from_sq)
        except ValueError:
            return []
        captures = [
            move
            for move in base
            if move.from_square == from_square and board.is_capture(move)
        ]
        if captures:
            return captures
        if stated_from:
            return []

    if slots.from_sq and slots.piece is not None:
        try:
            from_square = chess.parse_square(slots.from_sq)
        except ValueError:
            return []
        filtered = [
            move
            for move in base
            if move.from_square == from_square
            and board.piece_at(move.from_square)
            and board.piece_at(move.from_square).piece_type == slots.piece
        ]
        if filtered:
            return filtered
        if stated_from:
            return []

    if not stated_from and slots.piece is not None and slots.action == 'capture':
        filtered = [
            move
            for move in base
            if board.piece_at(move.from_square)
            and board.piece_at(move.from_square).piece_type == slots.piece
            and board.is_capture(move)
        ]
        if filtered:
            return filtered

    return []


def _move_to_parsed(move: chess.Move) -> VoiceMoveParsed:
    promo = ''
    if move.promotion:
        promo = chess.piece_symbol(move.promotion)
    return VoiceMoveParsed(
        from_sq=chess.square_name(move.from_square),
        to_sq=chess.square_name(move.to_square),
        promotion=promo,
    )


def parse_semantic_voice_move(
    transcript: str,
    fen: str,
    human_color: str,
    *,
    relaxed: bool = False,
) -> VoiceMoveParseResult:
    if not has_semantic_intent(transcript):
        return VoiceMoveParseError(kind='parse_error', message='no semantic intent')

    slots = extract_intent_slots(transcript, fen, human_color)
    candidates = filter_moves_by_intent(fen, human_color, slots)

    if len(candidates) == 1:
        return VoiceMoveParseOk(_move_to_parsed(candidates[0]))
    if len(candidates) > 1:
        return VoiceMoveParseError(
            kind='ambiguous',
            message=f'ambiguous intent ({len(candidates)} moves)',
        )

    if relaxed:
        relaxed_candidates = filter_moves_relaxed(fen, human_color, slots)
        if len(relaxed_candidates) == 1:
            return VoiceMoveParseOk(_move_to_parsed(relaxed_candidates[0]))
        if len(relaxed_candidates) > 1:
            return VoiceMoveParseError(
                kind='ambiguous',
                message=f'ambiguous relaxed intent ({len(relaxed_candidates)} moves)',
            )

    return VoiceMoveParseError(kind='parse_error', message='no move matches intent')


def validate_voice_move_intent(
    transcript: str,
    fen: str,
    human_color: str,
    parsed: VoiceMoveParsed,
) -> tuple[bool, str]:
    slots = extract_intent_slots(transcript, fen, human_color)
    board = chess.Board(fen)
    try:
        from_square = chess.parse_square(parsed.from_sq)
        to_square = chess.parse_square(parsed.to_sq)
    except ValueError:
        return False, 'invalid square'

    piece = board.piece_at(from_square)
    human_is_white = _human_is_white(human_color)
    if piece is None or piece.color != (chess.WHITE if human_is_white else chess.BLACK):
        return False, 'no human piece on from square'

    if slots.piece is not None and piece.piece_type != slots.piece:
        return False, 'piece type mismatch'

    move = chess.Move(from_square, to_square)
    if slots.action == 'capture' and board.is_legal(move) and not board.is_capture(move):
        return False, 'capture intent but move is not capture'

    return True, 'ok'


def format_intent_summary(slots: VoiceIntentSlots) -> str:
    parts: list[str] = []
    if slots.from_sq:
        parts.append(f'from={slots.from_sq}')
    if slots.to_sq:
        parts.append(f'to={slots.to_sq}')
    if slots.piece is not None:
        parts.append(f'piece={PIECE_TYPE_NAMES.get(slots.piece, "?")}')
    if slots.action:
        parts.append(f'action={slots.action}')
    if slots.target_piece is not None:
        parts.append(f'target={PIECE_TYPE_NAMES.get(slots.target_piece, "?")}')
    return ', '.join(parts) if parts else 'none'
