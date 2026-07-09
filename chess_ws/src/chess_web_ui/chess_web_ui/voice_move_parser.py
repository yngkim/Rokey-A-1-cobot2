"""Parse rule-based voice transcripts into chess move squares."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import chess

from chess_game.move_resolve import resolve_legal_uci_full

ParseErrorKind = Literal['parse_error', 'missing_squares', 'ambiguous']

KOREAN_FILE_MAP: dict[str, str] = {
    '에이': 'a',
    '알파': 'a',
    '비': 'b',
    '브라보': 'b',
    '씨': 'c',
    '시': 'c',
    '디': 'd',
    '델타': 'd',
    '이': 'e',
    '에': 'e',
    '에프': 'f',
    '프': 'f',
    '지': 'g',
    '쥐': 'g',
    '에이치': 'h',
    '에치': 'h',
}

PROMO_MAP: dict[str, str] = {
    'q': 'q',
    'queen': 'q',
    '퀸': 'q',
    'r': 'r',
    'rook': 'r',
    '룩': 'r',
    'b': 'b',
    'bishop': 'b',
    '비숍': 'b',
    'n': 'n',
    'knight': 'n',
    '나이트': 'n',
    '말': 'n',
}

PIECE_WORDS = (
    '폰',
    '나이트',
    '비숍',
    '룩',
    '퀸',
    '킹',
    'pawn',
    'knight',
    'bishop',
    'rook',
    'queen',
    'king',
    '말',
)

SQUARE_RE = re.compile(r'^[a-h][1-8]$')
UCI_RE = re.compile(r'^([a-h][1-8])([a-h][1-8])([qrbn])?$', re.IGNORECASE)


@dataclass(frozen=True)
class VoiceMoveParsed:
    from_sq: str
    to_sq: str
    promotion: str = ''


@dataclass(frozen=True)
class VoiceMoveParseOk:
    move: VoiceMoveParsed


@dataclass(frozen=True)
class VoiceMoveParseError:
    kind: ParseErrorKind
    message: str = ''


VoiceMoveParseResult = VoiceMoveParseOk | VoiceMoveParseError


def normalize_transcript(text: str) -> str:
    lowered = (text or '').strip().lower()
    if not lowered:
        return ''
    for korean, latin in sorted(KOREAN_FILE_MAP.items(), key=lambda item: -len(item[0])):
        lowered = lowered.replace(korean, latin)
    lowered = lowered.replace('에서', ' ')
    lowered = lowered.replace('로', ' ')
    lowered = lowered.replace('까지', ' ')
    lowered = lowered.replace('->', ' ')
    lowered = lowered.replace('→', ' ')
    lowered = lowered.replace('-', ' ')
    lowered = re.sub(r'[^\w\s가-힣]', ' ', lowered)
    for word in PIECE_WORDS:
        lowered = lowered.replace(word, ' ')
    lowered = re.sub(r'\s+', ' ', lowered).strip()
    return lowered


def _parse_square_token(token: str) -> str | None:
    token = token.strip().lower()
    if SQUARE_RE.match(token):
        return token
    return None


def _extract_squares(tokens: list[str]) -> list[str]:
    squares: list[str] = []
    for token in tokens:
        sq = _parse_square_token(token)
        if sq:
            squares.append(sq)
    return squares


def _parse_promotion_token(token: str) -> str:
    return PROMO_MAP.get(token.strip().lower(), '')


def parse_voice_move(transcript: str) -> VoiceMoveParseResult:
    normalized = normalize_transcript(transcript)
    if not normalized:
        return VoiceMoveParseError(
            kind='parse_error',
            message='empty transcript',
        )

    compact = normalized.replace(' ', '')
    uci_match = UCI_RE.match(compact)
    if uci_match:
        promo = (uci_match.group(3) or '').lower()
        return VoiceMoveParseOk(
            VoiceMoveParsed(
                from_sq=uci_match.group(1).lower(),
                to_sq=uci_match.group(2).lower(),
                promotion=promo,
            )
        )

    tokens = normalized.split()
    promo = ''
    if tokens:
        maybe_promo = _parse_promotion_token(tokens[-1])
        if maybe_promo and len(tokens) >= 3:
            promo = maybe_promo
            tokens = tokens[:-1]

    squares = _extract_squares(tokens)
    if len(squares) >= 2:
        return VoiceMoveParseOk(
            VoiceMoveParsed(from_sq=squares[0], to_sq=squares[1], promotion=promo)
        )
    if len(squares) == 1:
        return VoiceMoveParseError(
            kind='missing_squares',
            message='need both from and to squares',
        )

    return VoiceMoveParseError(
        kind='parse_error',
        message='could not parse move from transcript',
    )


def resolve_voice_move(
    fen: str,
    parsed: VoiceMoveParsed,
) -> tuple[str | None, bool, str]:
    """Return (legal_uci, promotion_required, message)."""
    board = chess.Board(fen)
    try:
        from_sq = chess.parse_square(parsed.from_sq)
        to_sq = chess.parse_square(parsed.to_sq)
    except ValueError:
        return None, False, 'invalid square'

    promo_type = None
    if parsed.promotion:
        promo_map = {
            'q': chess.QUEEN,
            'r': chess.ROOK,
            'b': chess.BISHOP,
            'n': chess.KNIGHT,
        }
        promo_type = promo_map.get(parsed.promotion.lower())

    candidates = [
        move
        for move in board.legal_moves
        if move.from_square == from_sq and move.to_square == to_sq
    ]
    if not candidates:
        return None, False, 'illegal move'

    promo_moves = [m for m in candidates if m.promotion]
    if promo_moves and promo_type is None:
        return None, True, 'promotion_required'

    if promo_type is not None:
        uci = f'{parsed.from_sq}{parsed.to_sq}{parsed.promotion.lower()}'
        legal = resolve_legal_uci_full(uci, fen)
        if legal is None:
            return None, False, 'illegal promotion'
        return legal, False, 'ok'

    if len(candidates) == 1:
        return candidates[0].uci(), False, 'ok'

    return None, False, 'ambiguous move'
