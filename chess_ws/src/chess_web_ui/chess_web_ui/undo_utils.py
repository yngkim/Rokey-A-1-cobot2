"""Helpers for undo snapshots and graveyard pick resolution."""

from __future__ import annotations

from typing import Any

from chess_web_ui.graveyard_utils import graveyard_fill_order, graveyard_slot_index


def copy_slots(slots: list[str | None] | None) -> list[str | None]:
    values = list(slots or [])
    if len(values) < 16:
        values.extend([None] * (16 - len(values)))
    return values[:16]


def make_ply_snapshot(
    *,
    fen: str,
    graveyard_slots: list[str | None],
    human_graveyard_slots: list[str | None],
    human_captures: list[str],
    robot_captures: list[str],
    move_history: list[dict[str, Any]],
    ply_counter: int,
    uci: str,
    by_robot: bool,
) -> dict[str, Any]:
    return {
        'fen': fen,
        'graveyard_slots': copy_slots(graveyard_slots),
        'human_graveyard_slots': copy_slots(human_graveyard_slots),
        'human_captures': list(human_captures),
        'robot_captures': list(robot_captures),
        'move_history': [dict(entry) for entry in move_history],
        'ply_counter': int(ply_counter),
        'uci': uci,
        'by_robot': bool(by_robot),
    }


def undo_ply_count(snapshots: list[dict[str, Any]]) -> int:
    """How many plies to undo to restore before the last human move."""
    if not snapshots:
        return 0
    last = snapshots[-1]
    if last.get('by_robot'):
        if len(snapshots) < 2 or snapshots[-2].get('by_robot'):
            raise ValueError('undo stack mismatch: robot move without preceding human move')
        return 2
    return 1


def find_graveyard_slot_for_symbol(
    slots: list[str | None],
    side: str,
    symbol: str,
) -> dict[str, Any] | None:
    """Find the most recently filled graveyard slot holding ``symbol`` (LIFO)."""
    normalized = copy_slots(slots)
    target = symbol.strip()
    for col, grave_row in reversed(graveyard_fill_order(side)):
        idx = graveyard_slot_index(col, grave_row)
        if normalized[idx] == target:
            return {
                'side': side.strip().lower(),
                'col': col,
                'grave_row': grave_row,
                'symbol': target,
            }
    return None


def graveyard_pick_from_diff(
    slots_before: list[str | None],
    slots_after: list[str | None],
    *,
    side: str,
) -> dict[str, Any] | None:
    """Find the slot filled between before→after along fill order (capture place)."""
    before = copy_slots(slots_before)
    after = copy_slots(slots_after)
    for col, grave_row in graveyard_fill_order(side):
        idx = graveyard_slot_index(col, grave_row)
        if before[idx] is None and after[idx] is not None:
            return {
                'side': side.strip().lower(),
                'col': col,
                'grave_row': grave_row,
                'symbol': after[idx],
            }
    return None


def resolve_capture_graveyard_pick(
    snap_before: dict[str, Any],
    snap_after_or_current: dict[str, Any],
    *,
    by_robot: bool,
    robot_side: str,
    human_side: str,
) -> dict[str, Any] | None:
    """Pick slot that received the captured piece for this ply.

    Robot capture → robot graveyard. Human capture → human graveyard.
    """
    if by_robot:
        return graveyard_pick_from_diff(
            snap_before['graveyard_slots'],
            snap_after_or_current['graveyard_slots'],
            side=robot_side,
        )
    return graveyard_pick_from_diff(
        snap_before['human_graveyard_slots'],
        snap_after_or_current['human_graveyard_slots'],
        side=human_side,
    )


def build_undo_moves_payload(
    snapshots: list[dict[str, Any]],
    *,
    current_fen: str,
    current_robot_gy: list[str | None],
    current_human_gy: list[str | None],
    robot_side: str,
    human_side: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (target_snapshot, newest-first undo move specs)."""
    n = undo_ply_count(snapshots)
    target = snapshots[-n]
    specs: list[dict[str, Any]] = []

    # Current board state after the last ply (for last capture GY diff).
    after_state = {
        'graveyard_slots': copy_slots(current_robot_gy),
        'human_graveyard_slots': copy_slots(current_human_gy),
    }

    for i in range(1, n + 1):
        snap = snapshots[-i]
        if i == 1:
            after = after_state
        else:
            # After undoing newer plies, state equals the previous snapshot... no:
            # For ply at index -i, "after" statewide is the next newer snap's "before"
            # which for i==1 is current; for i==2 is snapshots[-1] (state before robot move
            # = after human move) — use the Snap itself's GY after recording?
            # Snap stores state BEFORE the move.
            # After snap[-1] (robot) was made, GY = current.
            # After snap[-2] (human) was made, GY = snap[-1]'s NY? snap[-1] is state before
            # robot = state after human. Yes.
            after = {
                'graveyard_slots': copy_slots(snapshots[-i + 1]['graveyard_slots']),
                'human_graveyard_slots': copy_slots(
                    snapshots[-i + 1]['human_graveyard_slots']
                ),
            }
        pick = resolve_capture_graveyard_pick(
            snap,
            after,
            by_robot=bool(snap.get('by_robot')),
            robot_side=robot_side,
            human_side=human_side,
        )
        entry: dict[str, Any] = {
            'fen_before': snap['fen'],
            'uci': snap['uci'],
        }
        if pick is not None:
            entry['graveyard_pick'] = pick
        specs.append(entry)

    del current_fen  # unused, kept for API clarity
    return target, specs
