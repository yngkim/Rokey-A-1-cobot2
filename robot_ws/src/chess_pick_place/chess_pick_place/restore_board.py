"""Shared helpers for physical board restore."""

from __future__ import annotations

from chess_robot_motion.board_restore_planner import RestoreMove, needs_restore, plan_restore
from chess_robot_motion.board_state_manager import BoardStateManager
from chess_robot_motion.graveyard_state import GraveyardState


def plan_board_restore(
    board: BoardStateManager,
    robot_graveyard: GraveyardState,
    human_graveyard: GraveyardState | None = None,
) -> list[RestoreMove]:
    human_graveyard = human_graveyard or GraveyardState(side=_opponent_side(robot_graveyard.side))
    return plan_restore(
        board.fen,
        list(robot_graveyard.slots),
        robot_graveyard.side,
        human_slots=list(human_graveyard.slots),
        human_graveyard_side=human_graveyard.side,
    )


def board_needs_restore(
    board: BoardStateManager,
    robot_graveyard: GraveyardState,
    human_graveyard: GraveyardState | None = None,
) -> bool:
    human_graveyard = human_graveyard or GraveyardState(side=_opponent_side(robot_graveyard.side))
    return needs_restore(board.fen, list(robot_graveyard.slots), list(human_graveyard.slots))


def apply_restore_move_to_state(
    board: BoardStateManager,
    robot_graveyard: GraveyardState,
    move: RestoreMove,
    *,
    human_graveyard: GraveyardState | None = None,
) -> None:
    graveyard = robot_graveyard if move.graveyard_id == 'robot' else human_graveyard
    if graveyard is None:
        raise RuntimeError(f'missing graveyard state for {move.graveyard_id}')

    if move.kind == 'graveyard_to_board':
        symbol = graveyard.remove_piece(move.from_col, move.from_row)
        board.put_piece_at(move.to_col, move.to_row, symbol)
        return
    if move.kind == 'board_to_graveyard':
        symbol = board.remove_piece_at(move.from_col, move.from_row)
        if symbol is None:
            raise RuntimeError(f'no piece at board ({move.from_col},{move.from_row})')
        graveyard.place_piece(move.to_col, move.to_row, symbol)
        return
    if move.kind == 'board_to_board':
        symbol = board.remove_piece_at(move.from_col, move.from_row)
        if symbol is None:
            raise RuntimeError(f'no piece at board ({move.from_col},{move.from_row})')
        board.put_piece_at(move.to_col, move.to_row, symbol)
        return
    raise ValueError(f'unknown restore move kind: {move.kind}')


def _opponent_side(side: str) -> str:
    return 'white' if side.strip().lower() == 'black' else 'black'
