"""Plan physical moves to restore board + graveyard to starting position."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from chess_robot_motion.graveyard_pose_map import graveyard_fill_order
from chess_robot_motion.occupancy_grid import STARTING_FEN

RestoreKind = Literal['graveyard_to_board', 'board_to_board', 'board_to_graveyard']
GraveyardId = Literal['robot', 'human']


@dataclass(frozen=True)
class RestoreMove:
    kind: RestoreKind
    symbol: str
    from_col: int
    from_row: int
    to_col: int
    to_row: int
    graveyard_id: GraveyardId = 'robot'


def fen_to_piece_map(fen: str) -> dict[tuple[int, int], str]:
    board_rows = fen.split(' ')[0].split('/')
    pieces: dict[tuple[int, int], str] = {}
    for fen_row, row_str in enumerate(board_rows):
        col = 0
        for ch in row_str:
            if ch.isdigit():
                col += int(ch)
            else:
                row = 7 - fen_row
                pieces[(col, row)] = ch
                col += 1
    return pieces


def starting_homes_for_symbol(symbol: str, target: dict[tuple[int, int], str]) -> list[tuple[int, int]]:
    return sorted((sq for sq, sym in target.items() if sym == symbol), key=lambda sq: (sq[1], sq[0]))


def _graveyard_map(slots: list[str | None], side: str) -> dict[tuple[int, int], str]:
    fill_order = graveyard_fill_order(side)
    graveyard: dict[tuple[int, int], str] = {}
    for col, grave_row in fill_order:
        idx = grave_row * 8 + col
        if slots[idx]:
            graveyard[(col, grave_row)] = slots[idx]
    return graveyard


def _pick_surplus_square(
    symbol: str,
    current: dict[tuple[int, int], str],
    target: dict[tuple[int, int], str],
) -> tuple[int, int] | None:
    homes = set(starting_homes_for_symbol(symbol, target))
    for sq in sorted(current.keys(), key=lambda item: (item[1], item[0])):
        if current.get(sq) == symbol and sq not in homes:
            return sq
    for sq in starting_homes_for_symbol(symbol, target):
        if current.get(sq) == symbol:
            return sq
    return None


def _combined_graveyard_counts(
    robot_gy: dict[tuple[int, int], str],
    human_gy: dict[tuple[int, int], str],
) -> Counter[str]:
    return Counter(robot_gy.values()) + Counter(human_gy.values())


def _format_restore_failure(
    current: dict[tuple[int, int], str],
    robot_gy: dict[tuple[int, int], str],
    human_gy: dict[tuple[int, int], str],
    target: dict[tuple[int, int], str],
) -> str:
    target_counts = Counter(target.values())
    combined = _combined_graveyard_counts(robot_gy, human_gy)
    symbols = sorted(set(current.values()) | set(combined) | set(target.values()))
    parts: list[str] = []
    for symbol in symbols:
        board_n = sum(1 for piece in current.values() if piece == symbol)
        gy_n = combined.get(symbol, 0)
        target_n = target_counts.get(symbol, 0)
        if board_n + gy_n != target_n or board_n + gy_n > 0:
            parts.append(f'{symbol}: board={board_n} graveyard={gy_n} target={target_n}')
    detail = ', '.join(parts) if parts else 'no pieces'
    return f'could not plan full board restore ({detail})'


def needs_restore(
    current_fen: str,
    robot_slots: list[str | None],
    human_slots: list[str | None] | None = None,
    target_fen: str = STARTING_FEN,
) -> bool:
    if any(slots for slots in robot_slots):
        return True
    if human_slots and any(slots for slots in human_slots):
        return True
    return fen_to_piece_map(current_fen) != fen_to_piece_map(target_fen)


def plan_restore(
    current_fen: str,
    robot_slots: list[str | None],
    robot_graveyard_side: str,
    target_fen: str = STARTING_FEN,
    *,
    human_slots: list[str | None] | None = None,
    human_graveyard_side: str | None = None,
) -> list[RestoreMove]:
    human_slots = list(human_slots) if human_slots is not None else [None] * 16
    human_graveyard_side = human_graveyard_side or (
        'white' if robot_graveyard_side.strip().lower() == 'black' else 'black'
    )

    target = fen_to_piece_map(target_fen)
    current = fen_to_piece_map(current_fen)
    robot_fill = graveyard_fill_order(robot_graveyard_side)
    human_fill = graveyard_fill_order(human_graveyard_side)
    robot_gy = _graveyard_map(robot_slots, robot_graveyard_side)
    human_gy = _graveyard_map(human_slots, human_graveyard_side)
    moves: list[RestoreMove] = []

    def empty_robot_slot() -> tuple[int, int] | None:
        for col, grave_row in robot_fill:
            if (col, grave_row) not in robot_gy:
                return col, grave_row
        return None

    def empty_human_slot() -> tuple[int, int] | None:
        for col, grave_row in human_fill:
            if (col, grave_row) not in human_gy:
                return col, grave_row
        return None

    def board_to_graveyard(bcol: int, brow: int) -> None:
        slot = empty_robot_slot()
        gy_id: GraveyardId = 'robot'
        if slot is None:
            slot = empty_human_slot()
            gy_id = 'human'
        if slot is None:
            raise RuntimeError('graveyard full during restore planning')
        gcol, grow = slot
        symbol = current.pop((bcol, brow))
        if gy_id == 'robot':
            robot_gy[(gcol, grow)] = symbol
        else:
            human_gy[(gcol, grow)] = symbol
        moves.append(RestoreMove('board_to_graveyard', symbol, bcol, brow, gcol, grow, gy_id))

    def graveyard_to_board(
        gcol: int,
        grow: int,
        bcol: int,
        brow: int,
        *,
        gy_id: GraveyardId,
    ) -> None:
        if gy_id == 'robot':
            symbol = robot_gy.pop((gcol, grow))
        else:
            symbol = human_gy.pop((gcol, grow))
        current[(bcol, brow)] = symbol
        moves.append(RestoreMove('graveyard_to_board', symbol, gcol, grow, bcol, brow, gy_id))

    def board_to_board(fcol: int, frow: int, tcol: int, trow: int) -> None:
        symbol = current.pop((fcol, frow))
        current[(tcol, trow)] = symbol
        moves.append(RestoreMove('board_to_board', symbol, fcol, frow, tcol, trow))

    def available_homes(symbol: str) -> list[tuple[int, int]]:
        homes = starting_homes_for_symbol(symbol, target)
        empty = [sq for sq in homes if sq not in current]
        if empty:
            return empty
        return [sq for sq in homes if current.get(sq) != symbol]

    def take_home_for_symbol(symbol: str) -> tuple[int, int]:
        homes = available_homes(symbol)
        if homes:
            return homes[0]

        extra_sq = next(
            (
                sq
                for sq, piece in list(current.items())
                if piece == symbol and sq not in starting_homes_for_symbol(symbol, target)
            ),
            None,
        )
        if extra_sq is not None:
            board_to_graveyard(extra_sq[0], extra_sq[1])
            homes = available_homes(symbol)
            if homes:
                return homes[0]

        occupied_home = next(
            (
                sq
                for sq in starting_homes_for_symbol(symbol, target)
                if current.get(sq) is not None and current.get(sq) != symbol
            ),
            None,
        )
        if occupied_home is not None:
            board_to_graveyard(occupied_home[0], occupied_home[1])
            return occupied_home

        surplus = _pick_surplus_square(symbol, current, target)
        if surplus is not None:
            target_n = Counter(target.values()).get(symbol, 0)
            board_n = sum(1 for piece in current.values() if piece == symbol)
            gy_n = _combined_graveyard_counts(robot_gy, human_gy).get(symbol, 0)
            if board_n + gy_n > target_n:
                raise RuntimeError(
                    f'board FEN out of sync for {symbol!r}; sync vision FEN before restore'
                )
            board_to_graveyard(surplus[0], surplus[1])
            homes = available_homes(symbol)
            if homes:
                return homes[0]

        raise RuntimeError(f'no home square for graveyard piece {symbol!r}')

    all_squares = set(current.keys()) | set(target.keys())
    for sq in sorted(all_squares, key=lambda item: (item[1], item[0])):
        needed = target.get(sq)
        present = current.get(sq)
        if present is not None and present != needed:
            board_to_graveyard(sq[0], sq[1])

    def occupied_entries(
        gy: dict[tuple[int, int], str],
        fill: list[tuple[int, int]],
        gy_id: GraveyardId,
    ) -> list[tuple[int, int, str, GraveyardId]]:
        return [
            (col, grave_row, gy[(col, grave_row)], gy_id)
            for col, grave_row in fill
            if (col, grave_row) in gy
        ]

    occupied = occupied_entries(robot_gy, robot_fill, 'robot') + occupied_entries(
        human_gy, human_fill, 'human'
    )
    for gcol, grow, symbol, gy_id in reversed(occupied):
        if gy_id == 'robot' and (gcol, grow) not in robot_gy:
            continue
        if gy_id == 'human' and (gcol, grow) not in human_gy:
            continue
        home = take_home_for_symbol(symbol)
        if current.get(home) is not None:
            board_to_graveyard(home[0], home[1])
        graveyard_to_board(gcol, grow, home[0], home[1], gy_id=gy_id)

    for _ in range(64):
        if fen_to_piece_map_from_board(current) == target and not robot_gy and not human_gy:
            break
        progress = False
        for sq in sorted(list(current.keys()), key=lambda item: (item[1], item[0])):
            symbol = current[sq]
            needed = target.get(sq)
            if symbol == needed:
                continue
            dest = next(
                (
                    home_sq
                    for home_sq in starting_homes_for_symbol(symbol, target)
                    if home_sq != sq and current.get(home_sq) != symbol
                ),
                None,
            )
            if dest is None:
                continue
            if current.get(dest) is not None and current.get(dest) != symbol:
                board_to_graveyard(dest[0], dest[1])
            board_to_board(sq[0], sq[1], dest[0], dest[1])
            progress = True
            break
        if not progress:
            break

    if fen_to_piece_map_from_board(current) != target or robot_gy or human_gy:
        raise RuntimeError(_format_restore_failure(current, robot_gy, human_gy, target))

    return moves


def fen_to_piece_map_from_board(current: dict[tuple[int, int], str]) -> dict[tuple[int, int], str]:
    return dict(current)
