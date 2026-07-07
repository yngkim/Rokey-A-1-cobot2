"""Shared chess move resolution helpers (legal UCI, captures, game outcome)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import chess

DEFAULT_PROMOTION = chess.QUEEN

CASTLE_ROOK_SQUARES: dict[str, tuple[str, str]] = {
    'e1g1': ('h1', 'f1'),
    'e1c1': ('a1', 'd1'),
    'e8g8': ('h8', 'f8'),
    'e8c8': ('a8', 'd8'),
}

GameResultReason = Literal[
    'checkmate',
    'stalemate',
    'insufficient_material',
    'fifty_moves',
    'repetition',
    'draw',
]


@dataclass
class GameOutcome:
    is_over: bool
    result: str  # '1-0' | '0-1' | '1/2-1/2' | ''
    winner_side: str  # 'white' | 'black' | 'draw' | ''
    reason: GameResultReason | ''


def castle_rook_squares(uci4: str) -> tuple[str, str] | None:
    return CASTLE_ROOK_SQUARES.get(uci4)


def en_passant_capture_square(board: chess.Board, move: chess.Move) -> int | None:
    if not board.is_en_passant(move):
        return None
    return move.to_square + (-8 if board.turn == chess.WHITE else 8)


def relevant_changed_squares(board: chess.Board, move: chess.Move) -> set[str]:
    squares = {chess.square_name(move.from_square), chess.square_name(move.to_square)}
    uci4 = move.uci()[:4]
    rook = castle_rook_squares(uci4)
    if rook is not None:
        squares.update(rook)
    cap_sq = en_passant_capture_square(board, move)
    if cap_sq is not None:
        squares.add(chess.square_name(cap_sq))
    return squares


def resolve_legal_uci(
    fen: str,
    from_sq: str,
    to_sq: str,
    *,
    promotion: chess.PieceType | None = None,
) -> str | None:
    board = chess.Board(fen)
    try:
        from_square = chess.parse_square(from_sq)
        to_square = chess.parse_square(to_sq)
    except ValueError:
        return None

    candidates = [
        move
        for move in board.legal_moves
        if move.from_square == from_square and move.to_square == to_square
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].uci()

    if promotion is None:
        return None

    promoted = [move for move in candidates if move.promotion == promotion]
    if len(promoted) == 1:
        return promoted[0].uci()
    return None


def resolve_legal_uci_full(uci: str, fen: str) -> str | None:
    """Return legal UCI for a possibly partial UCI string against fen."""
    uci = uci.strip()
    if len(uci) < 4:
        return None
    from_sq, to_sq = uci[:2], uci[2:4]
    promo_char = uci[4:5] if len(uci) > 4 else ''
    promo_map = {'q': chess.QUEEN, 'r': chess.ROOK, 'b': chess.BISHOP, 'n': chess.KNIGHT}
    promotion = promo_map.get(promo_char)
    resolved = resolve_legal_uci(fen, from_sq, to_sq, promotion=promotion)
    if resolved is not None:
        return resolved
    if promo_char:
        return None
    return resolve_legal_uci(fen, from_sq, to_sq)


def captured_piece_symbol(board: chess.Board, move: chess.Move) -> str:
    cap_sq = en_passant_capture_square(board, move)
    if cap_sq is not None:
        piece = board.piece_at(cap_sq)
        return piece.symbol() if piece is not None else ''
    if board.is_capture(move):
        piece = board.piece_at(move.to_square)
        return piece.symbol() if piece is not None else ''
    return ''


def promotion_piece_char(move: chess.Move) -> str:
    if move.promotion is None:
        return ''
    return chess.piece_symbol(move.promotion).lower()


def promotion_notice(from_sq: str, to_sq: str, promotion_char: str) -> str:
    names = {'q': '퀸', 'r': '룩', 'b': '비숍', 'n': '나이트'}
    piece = names.get(promotion_char, promotion_char or '퀸')
    return f'승격: {from_sq}→{to_sq} ({piece}). 물리 기물은 폰으로 유지됩니다.'


def game_outcome(board: chess.Board) -> GameOutcome:
    if not board.is_game_over():
        return GameOutcome(is_over=False, result='', winner_side='', reason='')

    result = board.result(claim_draw=True)
    if board.is_checkmate():
        reason: GameResultReason = 'checkmate'
    elif board.is_stalemate():
        reason = 'stalemate'
    elif board.is_insufficient_material():
        reason = 'insufficient_material'
    elif board.can_claim_fifty_moves():
        reason = 'fifty_moves'
    elif board.can_claim_threefold_repetition():
        reason = 'repetition'
    else:
        reason = 'draw'

    if result == '1-0':
        winner = 'white'
    elif result == '0-1':
        winner = 'black'
    else:
        winner = 'draw'

    return GameOutcome(
        is_over=True,
        result=result,
        winner_side=winner,
        reason=reason,
    )


def parse_move_from_fen(fen: str, uci: str) -> chess.Move | None:
    board = chess.Board(fen)
    legal = resolve_legal_uci_full(uci, fen)
    if legal is None:
        return None
    return chess.Move.from_uci(legal)


def move_physics_flags(board: chess.Board, move: chess.Move) -> dict[str, object]:
    """Physical move metadata for robot execution."""
    uci4 = move.uci()[:4]
    flags: dict[str, object] = {
        'is_capture': board.is_capture(move),
        'is_en_passant': board.is_en_passant(move),
        'is_castling': board.is_castling(move),
        'promotion': promotion_piece_char(move),
        'capture_square': None,
        'rook_from': None,
        'rook_to': None,
    }
    cap_sq = en_passant_capture_square(board, move)
    if cap_sq is not None:
        flags['capture_square'] = chess.square_name(cap_sq)
        flags['is_capture'] = True
    rook = castle_rook_squares(uci4)
    if rook is not None:
        flags['rook_from'], flags['rook_to'] = rook
    return flags
