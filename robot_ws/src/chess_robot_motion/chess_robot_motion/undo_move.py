"""Plan physical reverse of a recently played UCI move."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import chess

from chess_robot_motion.move_physics import move_physics_flags, resolve_legal_uci_full


@dataclass(frozen=True)
class UndoStep:
    kind: str  # board_to_board | graveyard_to_board
    from_col: int
    from_row: int
    to_col: int
    to_row: int
    graveyard_side: str | None = None  # 'black'/'white' when from GY


def _sq_coords(name: str) -> tuple[int, int]:
    sq = chess.parse_square(name)
    return chess.square_file(sq), chess.square_rank(sq)


def plan_reverse_uci(
    fen_before: str,
    uci: str,
    *,
    graveyard_pick: dict[str, Any] | None = None,
) -> list[UndoStep]:
    """Return physical steps to undo ``uci`` that was played from ``fen_before``.

    Order:
      1. Return mover (and castle rook) from destination to origin
      2. If capture, return captured piece from graveyard to capture square
    """
    legal = resolve_legal_uci_full(uci, fen_before)
    if legal is None:
        raise ValueError(f'illegal undo uci {uci} for fen {fen_before}')
    board = chess.Board(fen_before)
    move = chess.Move.from_uci(legal)

    flags = move_physics_flags(board, move)
    from_col, from_row = _sq_coords(chess.square_name(move.from_square))
    to_col, to_row = _sq_coords(chess.square_name(move.to_square))

    steps: list[UndoStep] = [
        UndoStep('board_to_board', to_col, to_row, from_col, from_row),
    ]

    if flags.get('is_castling'):
        rook_from = flags.get('rook_from')
        rook_to = flags.get('rook_to')
        if isinstance(rook_from, str) and isinstance(rook_to, str):
            rf_c, rf_r = _sq_coords(rook_from)
            rt_c, rt_r = _sq_coords(rook_to)
            steps.append(UndoStep('board_to_board', rt_c, rt_r, rf_c, rf_r))

    if flags.get('is_capture'):
        if not graveyard_pick:
            raise ValueError(f'capture undo requires graveyard_pick for {legal}')
        cap_name = flags.get('capture_square')
        if not isinstance(cap_name, str):
            cap_name = chess.square_name(move.to_square)
        cap_col, cap_row = _sq_coords(cap_name)
        steps.append(
            UndoStep(
                'graveyard_to_board',
                int(graveyard_pick['col']),
                int(graveyard_pick['grave_row']),
                cap_col,
                cap_row,
                graveyard_side=str(graveyard_pick['side']).strip().lower(),
            )
        )

    return steps


def plan_reverse_physical(
    fen_before: str,
    from_sq: str,
    to_sq: str,
    *,
    graveyard_pick: dict[str, Any] | None = None,
) -> list[UndoStep]:
    """Return physical steps to undo an illegal occupancy change.

    Reverses the mover (``to`` -> ``from``). When ``fen_before`` had a piece on
    ``to`` and ``graveyard_pick`` is given, restores that piece from graveyard.
    """
    from_col, from_row = _sq_coords(from_sq)
    to_col, to_row = _sq_coords(to_sq)
    steps: list[UndoStep] = [
        UndoStep('board_to_board', to_col, to_row, from_col, from_row),
    ]

    board = chess.Board(fen_before)
    to_square = chess.parse_square(to_sq)
    if board.piece_at(to_square) is not None and graveyard_pick:
        cap_col, cap_row = to_col, to_row
        steps.append(
            UndoStep(
                'graveyard_to_board',
                int(graveyard_pick['col']),
                int(graveyard_pick['grave_row']),
                cap_col,
                cap_row,
                graveyard_side=str(graveyard_pick['side']).strip().lower(),
            )
        )

    return steps
