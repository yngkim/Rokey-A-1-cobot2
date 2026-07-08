"""Capture symbol resolution for graveyard / capture tracking."""

from __future__ import annotations

import chess

from chess_game.move_resolve import captured_piece_symbol, resolve_legal_uci_full


def resolve_capture_symbol(
    fen_before: str,
    uci: str,
    hinted: str | None,
) -> str:
    """Return captured piece symbol, or '' if the move is not a capture.

  Vision ``captured_piece`` hints are only accepted on real captures.
    """
    legal = resolve_legal_uci_full(uci, fen_before)
    if legal is None:
        return ''
    board = chess.Board(fen_before)
    move = chess.Move.from_uci(legal)
    inferred = captured_piece_symbol(board, move)
    if not inferred:
        return ''
    hint = (hinted or '').strip()
    if hint:
        try:
            chess.Piece.from_symbol(hint)
            return hint
        except ValueError:
            pass
    return inferred
