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


def guard_correction_fen(fen_before: str, fen: str) -> str:
    """Board correction edits piece placement only — never let a client-submitted
    FEN silently drop castling/halfmove/fullmove metadata (e.g. a stale/short
    source FEN on the frontend) and desync the move counter from move_history.

    That desync is unrecoverable downstream: the bot-move trust check rejects the
    FEN forever and the robot stops responding. If the submitted counters look
    regressed relative to the known board, keep the trusted counters and only
    take the edited placement/turn.
    """
    try:
        before = chess.Board(fen_before)
        candidate = chess.Board(fen)
    except ValueError:
        return fen
    if candidate.fullmove_number >= before.fullmove_number:
        return fen
    parts = fen.split()
    if len(parts) < 2:
        return fen
    placement, active = parts[0], parts[1]
    before_parts = fen_before.split()
    castling = before_parts[2] if len(before_parts) > 2 else '-'
    ep = before_parts[3] if len(before_parts) > 3 else '-'
    halfmove = before_parts[4] if len(before_parts) > 4 else '0'
    fullmove = before_parts[5] if len(before_parts) > 5 else '1'
    return f'{placement} {active} {castling} {ep} {halfmove} {fullmove}'
