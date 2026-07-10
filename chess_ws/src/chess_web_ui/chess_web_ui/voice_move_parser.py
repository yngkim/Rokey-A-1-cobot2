"""Parse rule-based voice transcripts into chess move squares."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import chess

from chess_game.move_resolve import resolve_legal_uci_full
from chess_web_ui.voice_stt_normalize import preprocess_transcript

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
    '에프': 'f',
    '지': 'g',
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

PIECE_WORD_PATTERN = re.compile(
    r'(?:'
    + '|'.join(re.escape(word) for word in PIECE_WORDS)
    + r')(?:을|를|이|가)?',
    re.IGNORECASE,
)
MOVE_HINT_PATTERN = re.compile(
    r'(?:잡|잡아|잡기|캡처|capture|먹|먹어|먹기|'
    r'전진|앞|앞으로|왼쪽|왼|오른쪽|오른|대각|대각선|'
    r'forward|left|right|diagonal|이동|옮)',
    re.IGNORECASE,
)

SQUARE_RE = re.compile(r'^[a-h][1-8]$')
SQUARE_ANY_RE = re.compile(r'[a-h][1-8]', re.IGNORECASE)
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
    lowered = preprocess_transcript(text)
    if not lowered:
        return ''
    for korean, latin in sorted(KOREAN_FILE_MAP.items(), key=lambda item: -len(item[0])):
        lowered = re.sub(
            rf'{re.escape(korean)}(?=[1-8])',
            latin,
            lowered,
            flags=re.IGNORECASE,
        )
    lowered = lowered.replace('에서', ' ')
    lowered = lowered.replace('까지', ' ')
    lowered = lowered.replace('->', ' ')
    lowered = lowered.replace('→', ' ')
    lowered = lowered.replace('-', ' ')
    lowered = re.sub(r'[^\w\s가-힣]', ' ', lowered)
    lowered = PIECE_WORD_PATTERN.sub(' ', lowered)
    lowered = re.sub(
        r'(?:의|을|를|이|가|에|으로|로|까지|에서|옮겨|옮기|이동|'
        r'해줘|해 주|주세요|줘|가|말해|말해봐|봐|놔)',
        ' ',
        lowered,
    )
    lowered = re.sub(r'\s+', ' ', lowered).strip()
    lowered = re.sub(r'([a-h][1-8])(?=[a-h][1-8])', r'\1 ', lowered)
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
            continue
        for match in re.finditer(r'([a-h])([1-8])', token, re.IGNORECASE):
            squares.append(f'{match.group(1).lower()}{match.group(2)}')
    return squares


def _parse_promotion_token(token: str) -> str:
    return PROMO_MAP.get(token.strip().lower(), '')


def _parse_rule_based(transcript: str) -> VoiceMoveParseResult:
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


def parse_voice_move(transcript: str) -> VoiceMoveParseResult:
    return _parse_rule_based(transcript)


def looks_like_chess_move_command(transcript: str) -> bool:
    preprocessed = preprocess_transcript(transcript)
    normalized = normalize_transcript(transcript)
    text = preprocessed or normalized
    if not text:
        return False

    compact = normalized.replace(' ', '')
    if UCI_RE.match(compact):
        return True
    if SQUARE_ANY_RE.search(text):
        return True
    if MOVE_HINT_PATTERN.search(text) and PIECE_WORD_PATTERN.search(text):
        return True
    return False


def parse_voice_command(
    transcript: str,
    *,
    fen: str | None = None,
    human_color: str = 'white',
    llm_enabled: bool = False,
    llm_auto: bool = True,
    llm_model: str = 'llama3.2:3b',
    llm_base_url: str = 'http://127.0.0.1:11434',
    llm_timeout_sec: float = 10.0,
) -> VoiceMoveParseResult:
    """Game routing is handled in web_bridge; this parses chess moves only."""
    result, _ = parse_voice_command_with_meta(
        transcript,
        fen=fen,
        human_color=human_color,
        llm_enabled=llm_enabled,
        llm_auto=llm_auto,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_timeout_sec=llm_timeout_sec,
    )
    return result


def parse_voice_command_with_meta(
    transcript: str,
    *,
    fen: str | None = None,
    human_color: str = 'white',
    llm_enabled: bool = False,
    llm_auto: bool = True,
    llm_model: str = 'llama3.2:3b',
    llm_base_url: str = 'http://127.0.0.1:11434',
    llm_timeout_sec: float = 10.0,
) -> tuple[VoiceMoveParseResult, str]:
    """Rule -> semantic(strict) -> semantic(relaxed) -> relative -> infer -> LLM."""
    from chess_web_ui.voice_semantic_parser import (
        extract_intent_slots,
        filter_moves_by_intent,
        filter_moves_relaxed,
        has_blocking_semantic_intent,
        has_semantic_intent,
        parse_semantic_voice_move,
        should_skip_relative,
    )

    fen_value = (fen or '').strip()
    semantic_intent = has_semantic_intent(transcript)
    if not semantic_intent and not looks_like_chess_move_command(transcript):
        return (
            VoiceMoveParseError(
                kind='parse_error',
                message='transcript does not look like a chess move command',
            ),
            'no_chess_intent',
        )

    rule_result = VoiceMoveParseError(kind='parse_error', message='skipped rule parser')
    if not semantic_intent:
        rule_result = _parse_rule_based(transcript)
        if isinstance(rule_result, VoiceMoveParseOk):
            return rule_result, 'rule'

    if fen_value and semantic_intent:
        strict = parse_semantic_voice_move(transcript, fen_value, human_color, relaxed=False)
        if isinstance(strict, VoiceMoveParseOk):
            return strict, 'semantic_strict'
        if strict.kind == 'ambiguous':
            slots = extract_intent_slots(transcript, fen_value, human_color)
            candidates = filter_moves_by_intent(fen_value, human_color, slots)
            if len(candidates) > 1:
                use_llm = llm_enabled or (llm_auto and fen_value)
                if use_llm:
                    from chess_web_ui.voice_llm_parser import ollama_available, parse_voice_move_llm

                    if llm_enabled or ollama_available(llm_base_url):
                        llm_result = parse_voice_move_llm(
                            transcript,
                            fen_value,
                            human_color,
                            model=llm_model,
                            base_url=llm_base_url,
                            timeout_sec=llm_timeout_sec,
                            slots=slots,
                            candidate_moves=candidates,
                            allow_full_legal_list=False,
                        )
                        if isinstance(llm_result, VoiceMoveParseOk):
                            return llm_result, 'llm_candidates'
                return strict, 'semantic_ambiguous'

        relaxed = parse_semantic_voice_move(transcript, fen_value, human_color, relaxed=True)
        if isinstance(relaxed, VoiceMoveParseOk):
            return relaxed, 'semantic_relaxed'
        if relaxed.kind == 'ambiguous':
            slots = extract_intent_slots(transcript, fen_value, human_color)
            relaxed_candidates = filter_moves_relaxed(fen_value, human_color, slots)
            if len(relaxed_candidates) > 1:
                use_llm = llm_enabled or (llm_auto and fen_value)
                if use_llm:
                    from chess_web_ui.voice_llm_parser import ollama_available, parse_voice_move_llm

                    if llm_enabled or ollama_available(llm_base_url):
                        llm_result = parse_voice_move_llm(
                            transcript,
                            fen_value,
                            human_color,
                            model=llm_model,
                            base_url=llm_base_url,
                            timeout_sec=llm_timeout_sec,
                            slots=slots,
                            candidate_moves=relaxed_candidates,
                            allow_full_legal_list=False,
                        )
                        if isinstance(llm_result, VoiceMoveParseOk):
                            return llm_result, 'llm_relaxed_candidates'
            return relaxed, 'semantic_relaxed_ambiguous'

    if fen_value and not should_skip_relative(transcript):
        from chess_web_ui.voice_relative_parser import parse_relative_voice_move

        relative = parse_relative_voice_move(transcript, fen_value, human_color)
        if isinstance(relative, VoiceMoveParseOk):
            return relative, 'relative'

    if fen_value:
        from chess_web_ui.voice_infer_parser import infer_voice_move

        inferred = infer_voice_move(transcript, fen_value, human_color)
        if isinstance(inferred, VoiceMoveParseOk):
            return inferred, 'infer'

    slots = extract_intent_slots(transcript, fen_value or None, human_color)
    strict_candidates = (
        filter_moves_by_intent(fen_value, human_color, slots) if fen_value else []
    )
    relaxed_candidates = (
        filter_moves_relaxed(fen_value, human_color, slots) if fen_value else []
    )
    all_candidates = strict_candidates or relaxed_candidates

    if fen_value and has_blocking_semantic_intent(transcript) and not all_candidates:
        return (
            VoiceMoveParseError(
                kind='parse_error',
                message='capture/piece intent has no matching legal move',
            ),
            'blocked_no_candidates',
        )

    use_llm = llm_enabled or (llm_auto and fen_value)
    if use_llm and fen_value:
        from chess_web_ui.voice_llm_parser import ollama_available, parse_voice_move_llm

        if llm_enabled or ollama_available(llm_base_url):
            allow_full = not has_blocking_semantic_intent(transcript)
            llm_result = parse_voice_move_llm(
                transcript,
                fen_value,
                human_color,
                model=llm_model,
                base_url=llm_base_url,
                timeout_sec=llm_timeout_sec,
                slots=slots,
                candidate_moves=all_candidates if all_candidates else None,
                allow_full_legal_list=allow_full,
            )
            if isinstance(llm_result, VoiceMoveParseOk):
                return llm_result, 'llm'
            if llm_enabled and llm_result.message and 'llm unavailable' not in llm_result.message:
                return llm_result, 'llm_error'

    if isinstance(rule_result, VoiceMoveParseOk):
        return rule_result, 'rule'
    return rule_result, 'parse_error'


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
