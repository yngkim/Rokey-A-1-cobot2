"""Optional Ollama LLM fallback for natural-language chess voice commands."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

import chess

from chess_web_ui.voice_move_parser import (
    VoiceMoveParseError,
    VoiceMoveParseOk,
    VoiceMoveParsed,
    VoiceMoveParseResult,
)
from chess_web_ui.voice_semantic_parser import (
    VoiceIntentSlots,
    extract_intent_slots,
    filter_moves_by_intent,
    format_intent_summary,
)

_JSON_BLOCK_RE = re.compile(r'\{[^{}]*\}', re.DOTALL)

_PIECE_LABELS = {
    chess.PAWN: 'pawn',
    chess.KNIGHT: 'knight',
    chess.BISHOP: 'bishop',
    chess.ROOK: 'rook',
    chess.QUEEN: 'queen',
    chess.KING: 'king',
}


def _human_is_white(human_color: str) -> bool:
    return human_color.strip().lower() != 'black'


def _human_legal_moves(fen: str, human_color: str) -> list[chess.Move]:
    board = chess.Board(fen)
    human_is_white = _human_is_white(human_color)
    if board.turn != (chess.WHITE if human_is_white else chess.BLACK):
        return []
    return list(board.legal_moves)


def _piece_label(board: chess.Board, square: int) -> str:
    piece = board.piece_at(square)
    if piece is None:
        return 'empty'
    color = 'white' if piece.color == chess.WHITE else 'black'
    return f'{color} {_PIECE_LABELS[piece.piece_type]}'


def _board_summary(fen: str, human_color: str) -> str:
    board = chess.Board(fen)
    human_is_white = _human_is_white(human_color)
    human_color_flag = chess.WHITE if human_is_white else chess.BLACK
    pieces: list[str] = []
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None or piece.color != human_color_flag:
            continue
        pieces.append(f'{chess.square_name(square)}: {_piece_label(board, square)}')
    return ', '.join(pieces[:32]) if pieces else 'none'


def _annotate_move(board: chess.Board, move: chess.Move) -> str:
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)
    mover = board.piece_at(move.from_square)
    mover_name = _PIECE_LABELS[mover.piece_type] if mover else 'piece'
    uci = move.uci()
    if board.is_capture(move):
        captured = board.piece_at(move.to_square)
        captured_name = _PIECE_LABELS[captured.piece_type] if captured else 'piece'
        return f'{uci} ({mover_name} {from_sq} captures {captured_name} {to_sq})'
    return f'{uci} ({mover_name} {from_sq}->{to_sq})'


def _annotated_move_summary(
    fen: str,
    moves: list[chess.Move],
    *,
    limit: int = 48,
) -> str:
    if not moves:
        return 'none'
    board = chess.Board(fen)
    lines = [_annotate_move(board, move) for move in moves[:limit]]
    if len(moves) > limit:
        lines.append(f'... ({len(moves)} total)')
    return '\n'.join(lines)


def _legal_move_summary(fen: str, human_color: str, *, limit: int = 64) -> str:
    moves = _human_legal_moves(fen, human_color)
    return _annotated_move_summary(fen, moves, limit=limit)


def build_voice_llm_prompt(
    transcript: str,
    fen: str,
    human_color: str,
    *,
    slots: VoiceIntentSlots | None = None,
    candidate_moves: list[chess.Move] | None = None,
) -> str:
    if candidate_moves is None and slots is not None:
        candidate_moves = filter_moves_by_intent(fen, human_color, slots)

    if candidate_moves is not None:
        move_block = _annotated_move_summary(fen, candidate_moves)
        candidate_note = f'Candidate moves (pick one):\n{move_block}'
    else:
        candidate_note = f'Legal moves (pick one):\n{_legal_move_summary(fen, human_color)}'

    intent_line = ''
    if slots is not None:
        summary = format_intent_summary(slots)
        if summary != 'none':
            intent_line = f'Parsed intent: {summary}\n'

    return (
        'Convert the chess voice command into one legal move JSON.\n'
        f'Human color: {human_color}\n'
        f'FEN: {fen}\n'
        f'Human pieces: {_board_summary(fen, human_color)}\n'
        f'{intent_line}'
        f'{candidate_note}\n'
        'Reply with ONLY JSON.\n'
        'Success: {"from":"a2","to":"a3","promotion":""}\n'
        'Failure: {"error":"reason"}\n'
        'Rules:\n'
        '- Use lowercase squares.\n'
        '- promotion is q|r|b|n or empty string.\n'
        '- Pick exactly one move from the candidate/legal list.\n'
        'Examples:\n'
        '- "a2의 폰을 a3로 옮겨줘" -> {"from":"a2","to":"a3","promotion":""}\n'
        '- "f3 나이트로 폰 잡아줘" -> knight on f3 captures the only legal pawn capture\n'
        '- "비숍으로 폰 잡아줘" -> pick the unique bishop capture of a pawn\n'
        '- If multiple moves still match, return {"error":"ambiguous"}\n'
        f'Command: {transcript.strip()}'
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or '').strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def ollama_available(base_url: str, *, timeout_sec: float = 0.4) -> bool:
    url = base_url.rstrip('/') + '/api/tags'
    request = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _ollama_generate(
    prompt: str,
    *,
    model: str,
    base_url: str,
    timeout_sec: float,
) -> str:
    url = base_url.rstrip('/') + '/api/generate'
    body = json.dumps({
        'model': model,
        'prompt': prompt,
        'stream': False,
        'format': 'json',
        'options': {'temperature': 0, 'num_predict': 120},
    }).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode('utf-8'))
    return str(payload.get('response', '')).strip()


def _match_legal_move(
    fen: str,
    human_color: str,
    from_sq: str,
    to_sq: str,
    promotion: str,
    *,
    allowed_moves: list[chess.Move] | None = None,
) -> chess.Move | None:
    try:
        from_square = chess.parse_square(from_sq)
        to_square = chess.parse_square(to_sq)
    except ValueError:
        return None

    promo_map = {
        'q': chess.QUEEN,
        'r': chess.ROOK,
        'b': chess.BISHOP,
        'n': chess.KNIGHT,
    }
    promo_type = promo_map.get(promotion.lower()) if promotion else None

    search_moves = allowed_moves if allowed_moves is not None else _human_legal_moves(fen, human_color)
    for move in search_moves:
        if move.from_square != from_square or move.to_square != to_square:
            continue
        if promo_type is None and move.promotion is None:
            return move
        if move.promotion == promo_type:
            return move
    return None


def _parsed_from_move(move: chess.Move) -> VoiceMoveParseOk:
    promo = ''
    if move.promotion:
        promo = chess.piece_symbol(move.promotion)
    return VoiceMoveParseOk(
        VoiceMoveParsed(
            from_sq=chess.square_name(move.from_square),
            to_sq=chess.square_name(move.to_square),
            promotion=promo,
        )
    )


def parse_voice_move_llm(
    transcript: str,
    fen: str,
    human_color: str,
    *,
    model: str = 'llama3.2:3b',
    base_url: str = 'http://127.0.0.1:11434',
    timeout_sec: float = 10.0,
    generate_fn: Callable[..., str] = _ollama_generate,
    slots: VoiceIntentSlots | None = None,
    candidate_moves: list[chess.Move] | None = None,
    allow_full_legal_list: bool = True,
) -> VoiceMoveParseResult:
    transcript = (transcript or '').strip()
    if not transcript:
        return VoiceMoveParseError(kind='parse_error', message='empty transcript')
    if not fen.strip():
        return VoiceMoveParseError(kind='parse_error', message='missing FEN for LLM parse')

    intent_slots = slots if slots is not None else extract_intent_slots(transcript, fen, human_color)
    filtered: list[chess.Move]
    if candidate_moves is not None:
        filtered = candidate_moves
    else:
        filtered = filter_moves_by_intent(fen, human_color, intent_slots)

    if len(filtered) == 1:
        return _parsed_from_move(filtered[0])

    if not filtered and not allow_full_legal_list:
        return VoiceMoveParseError(
            kind='parse_error',
            message='llm blocked: no candidate moves for capture/piece intent',
        )

    prompt = build_voice_llm_prompt(
        transcript,
        fen,
        human_color,
        slots=intent_slots,
        candidate_moves=filtered if filtered else None,
    )
    try:
        raw = generate_fn(
            prompt,
            model=model,
            base_url=base_url,
            timeout_sec=timeout_sec,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return VoiceMoveParseError(
            kind='parse_error',
            message=f'llm unavailable: {exc}',
        )

    payload = _extract_json_object(raw)
    if payload is None:
        return VoiceMoveParseError(kind='parse_error', message='llm returned invalid JSON')

    if payload.get('error'):
        return VoiceMoveParseError(
            kind='parse_error',
            message=str(payload.get('error')),
        )

    from_sq = str(payload.get('from', '')).strip().lower()
    to_sq = str(payload.get('to', '')).strip().lower()
    promotion = str(payload.get('promotion', '') or '').strip().lower()
    if not re.match(r'^[a-h][1-8]$', from_sq) or not re.match(r'^[a-h][1-8]$', to_sq):
        return VoiceMoveParseError(kind='parse_error', message='llm squares invalid')

    allowed = filtered if filtered else None
    move = _match_legal_move(
        fen,
        human_color,
        from_sq,
        to_sq,
        promotion,
        allowed_moves=allowed,
    )
    if move is None:
        return VoiceMoveParseError(kind='parse_error', message='llm move not legal')

    return _parsed_from_move(move)
