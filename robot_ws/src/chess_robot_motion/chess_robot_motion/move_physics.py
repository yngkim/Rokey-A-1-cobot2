"""Chess move physics metadata for robot execution."""

from __future__ import annotations

import chess

DEFAULT_PROMOTION = chess.QUEEN

CASTLE_ROOK_SQUARES: dict[str, tuple[str, str]] = {
    'e1g1': ('h1', 'f1'),
    'e1c1': ('a1', 'd1'),
    'e8g8': ('h8', 'f8'),
    'e8c8': ('a8', 'd8'),
}


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

    promo = promotion or DEFAULT_PROMOTION
    promoted = [move for move in candidates if move.promotion == promo]
    if len(promoted) == 1:
        return promoted[0].uci()
    return None


def resolve_legal_uci_full(uci: str, fen: str) -> str | None:
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


def en_passant_capture_square(board: chess.Board, move: chess.Move) -> int | None:
    if not board.is_en_passant(move):
        return None
    return move.to_square + (-8 if board.turn == chess.WHITE else 8)


def captured_piece_symbol(board: chess.Board, move: chess.Move) -> str:
    cap_sq = en_passant_capture_square(board, move)
    if cap_sq is not None:
        piece = board.piece_at(cap_sq)
        return piece.symbol() if piece is not None else ''
    if board.is_capture(move):
        piece = board.piece_at(move.to_square)
        return piece.symbol() if piece is not None else ''
    return ''


def move_physics_flags(board: chess.Board, move: chess.Move) -> dict[str, object]:
    uci4 = move.uci()[:4]
    flags: dict[str, object] = {
        'is_capture': board.is_capture(move),
        'is_en_passant': board.is_en_passant(move),
        'is_castling': board.is_castling(move),
        'promotion': chess.piece_symbol(move.promotion).lower() if move.promotion else '',
        'capture_square': None,
        'rook_from': None,
        'rook_to': None,
    }
    cap_sq = en_passant_capture_square(board, move)
    if cap_sq is not None:
        flags['capture_square'] = chess.square_name(cap_sq)
        flags['is_capture'] = True
    rook = CASTLE_ROOK_SQUARES.get(uci4)
    if rook is not None:
        flags['rook_from'], flags['rook_to'] = rook
    return flags
