"""Square index helpers for an 8x8 board."""

from __future__ import annotations

import chess


def index_to_square_name(index: int) -> str:
    col = index % 8
    row = index // 8
    return f'{chr(ord("a") + col)}{row + 1}'


def square_name_to_index(name: str) -> int:
    col = ord(name[0]) - ord('a')
    row = int(name[1]) - 1
    return row * 8 + col


def square_msg_to_chess_square(square_msg) -> int:
    return chess.square(square_msg.col, square_msg.row)


def occupancy_from_fen(fen: str) -> list[bool]:
    """Return 64 booleans: True where the FEN has any piece."""
    board = chess.Board(fen)
    return [board.piece_at(square) is not None for square in chess.SQUARES]
