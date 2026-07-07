"""Reconcile graveyard slot state when the board FEN is manually corrected."""

from __future__ import annotations

from collections import Counter

from chess_web_ui.graveyard_utils import graveyard_fill_order, graveyard_slot_index


def piece_counts_from_fen(fen: str) -> Counter[str]:
    placement = fen.split(' ')[0]
    counts: Counter[str] = Counter()
    for ch in placement:
        if ch.isalpha():
            counts[ch] += 1
    return counts


def _remove_symbol_lifo(
    slots: list[str | None],
    side: str,
    symbol: str,
    count: int,
) -> int:
    """Remove up to count symbols from graveyard slots (LIFO). Returns removed count."""
    if count <= 0:
        return 0
    removed = 0
    fill_order = list(reversed(graveyard_fill_order(side)))
    for col, grave_row in fill_order:
        if removed >= count:
            break
        idx = graveyard_slot_index(col, grave_row)
        if slots[idx] == symbol:
            slots[idx] = None
            removed += 1
    return removed


def reconcile_graveyards_with_fen(
    fen_before: str,
    fen_after: str,
    robot_slots: list[str | None],
    human_slots: list[str | None],
    *,
    robot_side: str,
    human_side: str,
) -> tuple[list[str | None], list[str | None]]:
    """When pieces reappear on the board, remove them from graveyards (LIFO)."""
    before = piece_counts_from_fen(fen_before)
    after = piece_counts_from_fen(fen_after)
    robot_out = list(robot_slots)
    human_out = list(human_slots)

    symbols = set(before) | set(after)
    for symbol in symbols:
        gained_on_board = after[symbol] - before[symbol]
        if gained_on_board <= 0:
            continue
        remaining = gained_on_board
        removed = _remove_symbol_lifo(robot_out, robot_side, symbol, remaining)
        remaining -= removed
        if remaining > 0:
            _remove_symbol_lifo(human_out, human_side, symbol, remaining)

    return robot_out, human_out
