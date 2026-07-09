"""Helpers for manual board correction flows."""

from __future__ import annotations

import chess


def piece_placement(fen: str) -> str:
    return fen.split()[0]


def infer_human_move_uci(fen_before: str, fen_after: str, human_color: str) -> str | None:
    """Infer exactly one human legal move that explains a board correction.

    Compares only piece placement so a wrong active-color toggle in the edited
    FEN does not block recovery after the user sets the post-move position.
    """
    board_before = chess.Board(fen_before)
    human_is_white = human_color.strip().lower() == 'white'
    if board_before.turn != (chess.WHITE if human_is_white else chess.BLACK):
        return None

    target = piece_placement(fen_after)
    if target == piece_placement(fen_before):
        return None

    candidates: list[str] = []
    for move in board_before.legal_moves:
        trial = board_before.copy()
        trial.push(move)
        if piece_placement(trial.fen()) == target:
            candidates.append(move.uci())

    if len(candidates) == 1:
        return candidates[0]
    return None
