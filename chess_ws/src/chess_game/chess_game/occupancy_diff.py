"""Infer chess moves from occupancy grid diffs (depth / vision)."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_game.board_utils import index_to_square_name, square_name_to_index
from chess_game.move_resolve import captured_piece_symbol, resolve_legal_uci


@dataclass
class DiffMoveResult:
    from_square: str
    to_square: str
    departed: list[str]
    arrived: list[str]
    confident: bool
    via_inference: bool = False


def _departed_arrived(
    previous_cells: list[bool],
    current_cells: list[bool],
) -> tuple[list[str], list[str]]:
    departed: list[str] = []
    arrived: list[str] = []
    for idx, (prev, curr) in enumerate(zip(previous_cells, current_cells)):
        if prev and not curr:
            departed.append(index_to_square_name(idx))
        elif not prev and curr:
            arrived.append(index_to_square_name(idx))
    return departed, arrived


def _pawn_rank_bonus(from_row: int, to_row: int, white_to_move: bool) -> int:
    """Prefer back-rank pawns for two-square pushes (e2-e4, d7-d5)."""
    if white_to_move and from_row == 1 and to_row > from_row:
        return -8
    if not white_to_move and from_row == 6 and to_row < from_row:
        return -8
    return 0


def _same_file_candidates(
    previous_cells: list[bool],
    to_square: str,
    *,
    white_to_move: bool,
) -> list[str]:
    to_col = ord(to_square[0]) - ord('a')
    to_row = int(to_square[1]) - 1
    scored: list[tuple[float, str]] = []

    for row in range(8):
        if row == to_row:
            continue
        if white_to_move and row >= to_row:
            continue
        if not white_to_move and row <= to_row:
            continue
        idx = row * 8 + to_col
        if not previous_cells[idx]:
            continue
        dist = abs(to_row - row)
        score = dist + _pawn_rank_bonus(row, to_row, white_to_move)
        scored.append((score, index_to_square_name(idx)))

    scored.sort(key=lambda item: item[0])
    return [name for _, name in scored]


def _infer_from_square(
    previous_cells: list[bool],
    to_square: str,
    fen: str,
) -> str | None:
    to_row = int(to_square[1]) - 1
    best_name: str | None = None
    best_score: float | None = None

    for white_to_move in (True, False):
        for name in _same_file_candidates(
            previous_cells,
            to_square,
            white_to_move=white_to_move,
        ):
            from_row = int(name[1]) - 1
            score = float(abs(to_row - from_row))
            score += float(_pawn_rank_bonus(from_row, to_row, white_to_move))
            if white_to_move and from_row <= 2 and to_row > from_row:
                score -= 4.0
            if not white_to_move and from_row >= 5 and to_row < from_row:
                score -= 4.0
            if best_score is None or score < best_score:
                best_score = score
                best_name = name

    if best_name is not None:
        return best_name

    to_idx = square_name_to_index(to_square)
    to_col = to_idx % 8
    to_row = to_idx // 8
    nearby: list[tuple[int, str]] = []
    for idx, occupied in enumerate(previous_cells):
        if not occupied:
            continue
        row = idx // 8
        col = idx % 8
        dist = abs(row - to_row) + abs(col - to_col)
        if dist == 0 or dist > 4:
            continue
        nearby.append((dist, index_to_square_name(idx)))
    if not nearby:
        return None
    nearby.sort(key=lambda item: item[0])
    return nearby[0][1]


def _legal_destination_for_departed(
    from_sq: str,
    current_cells: list[bool],
    previous_cells: list[bool],
    fen: str,
) -> str | None:
    """Pick destination using legal moves (captures rank above occupancy heuristics)."""
    board = chess.Board(fen)
    try:
        from_square = chess.parse_square(from_sq)
    except ValueError:
        return None

    scored: list[tuple[int, str]] = []
    for move in board.legal_moves:
        if move.from_square != from_square:
            continue
        to_name = chess.square_name(move.to_square)
        to_idx = square_name_to_index(to_name)
        if not current_cells[to_idx]:
            continue
        score = chess.square_distance(from_square, move.to_square)
        if board.is_capture(move):
            score -= 20
        if previous_cells[to_idx]:
            score -= 10
        scored.append((score, to_name))

    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    best_score = scored[0][0]
    top = [name for score, name in scored if score <= best_score + 1]
    if len(top) == 1:
        return top[0]
    captures = [
        name
        for score, name in scored
        if score <= best_score + 1 and board.is_capture(chess.Move.from_uci(f'{from_sq}{name}'))
    ]
    if len(captures) == 1:
        return captures[0]
    return scored[0][1]


def _pair_two_departed_capture(
    departed: list[str],
    fen: str,
) -> tuple[str, str] | None:
    """Victim removed to graveyard; attacker may not register as arrived (2 departed, 0 arrived)."""
    if len(departed) != 2:
        return None

    board = chess.Board(fen)
    for from_sq in departed:
        for victim_sq in departed:
            if victim_sq == from_sq:
                continue
            try:
                move = chess.Move.from_uci(f'{from_sq}{victim_sq}')
            except ValueError:
                continue
            if move in board.legal_moves and board.is_capture(move):
                return from_sq, victim_sq
    return None


def _infer_to_square(
    previous_cells: list[bool],
    current_cells: list[bool],
    from_square: str,
    fen: str,
) -> str | None:
    legal_to = _legal_destination_for_departed(from_square, current_cells, previous_cells, fen)
    if legal_to is not None:
        return legal_to

    board = chess.Board(fen)
    from_idx = square_name_to_index(from_square)
    from_col = from_idx % 8
    from_row = from_idx // 8
    white_to_move = board.turn == chess.WHITE

    scored: list[tuple[int, str]] = []
    for idx, curr in enumerate(current_cells):
        if not curr:
            continue
        row = idx // 8
        col = idx % 8
        if col == from_col:
            if white_to_move and row <= from_row:
                continue
            if not white_to_move and row >= from_row:
                continue
        dist = abs(row - from_row) + abs(col - from_col)
        if dist == 0 or dist > 4:
            continue
        was_occupied = previous_cells[idx]
        bonus = 0 if was_occupied else -1
        try:
            move = chess.Move.from_uci(f'{from_square}{index_to_square_name(idx)}')
            if move in board.legal_moves and board.is_capture(move):
                bonus -= 15
        except ValueError:
            pass
        scored.append((dist + bonus, index_to_square_name(idx)))

    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _pair_capture_move(
    departed: list[str],
    arrived: list[str],
    fen: str,
) -> tuple[str, str] | None:
    """Resolve from/to when a capture clears the destination (2 departed, 1 arrived)."""
    if len(departed) != 2 or len(arrived) != 1:
        return None

    to_sq = arrived[0]
    from_candidates = [sq for sq in departed if sq != to_sq]
    if not from_candidates:
        return None

    board = chess.Board(fen)
    legal: list[tuple[str, str]] = []
    for from_sq in from_candidates:
        try:
            move = chess.Move.from_uci(f'{from_sq}{to_sq}')
        except ValueError:
            continue
        if move in board.legal_moves:
            legal.append((from_sq, to_sq))

    if len(legal) == 1:
        return legal[0]
    if len(legal) > 1:
        captures = [pair for pair in legal if board.is_capture(chess.Move.from_uci(f'{pair[0]}{pair[1]}'))]
        if len(captures) == 1:
            return captures[0]
        return legal[0]

    for from_sq in from_candidates:
        try:
            piece = board.piece_at(chess.parse_square(from_sq))
        except ValueError:
            continue
        if piece is not None and piece.color == board.turn:
            return from_sq, to_sq

    return _pair_departed_arrived(departed, arrived)


def infer_captured_piece(
    fen: str,
    from_sq: str,
    to_sq: str,
    *,
    departed: list[str] | None = None,
    baseline: list[bool] | None = None,
) -> str:
    """Return FEN symbol of captured piece, or '' if not a capture."""
    del departed, baseline
    board = chess.Board(fen)
    uci = resolve_legal_uci(fen, from_sq, to_sq)
    if uci is not None:
        move = chess.Move.from_uci(uci)
        return captured_piece_symbol(board, move)
    return ''


def _pair_departed_arrived(
    departed: list[str],
    arrived: list[str],
) -> tuple[str, str] | None:
    if not departed or not arrived:
        return None
    if len(departed) == 1 and len(arrived) == 1:
        return departed[0], arrived[0]

    best: tuple[int, str, str] | None = None
    for from_sq in departed:
        from_idx = square_name_to_index(from_sq)
        fr, fc = from_idx // 8, from_idx % 8
        for to_sq in arrived:
            to_idx = square_name_to_index(to_sq)
            tr, tc = to_idx // 8, to_idx % 8
            dist = abs(fr - tr) + abs(fc - tc)
            if dist == 0 or dist > 6:
                continue
            if best is None or dist < best[0]:
                best = (dist, from_sq, to_sq)
    if best is None:
        return None
    return best[1], best[2]


def _filter_arrived_by_legal_moves(
    departed: list[str],
    arrived: list[str],
    fen: str,
) -> list[str]:
    """Remove depth false-positives when one piece left and multiple squares look occupied."""
    if len(departed) != 1 or len(arrived) < 2:
        return arrived

    board = chess.Board(fen)
    from_sq = departed[0]
    try:
        from_square = chess.parse_square(from_sq)
    except ValueError:
        return arrived

    legal_destinations = {
        chess.square_name(move.to_square)
        for move in board.legal_moves
        if move.from_square == from_square
    }
    if not legal_destinations:
        return arrived

    filtered = [sq for sq in arrived if sq in legal_destinations]
    return filtered if filtered else arrived


def detect_move_from_diff(
    previous_cells: list[bool],
    current_cells: list[bool],
    fen: str,
) -> DiffMoveResult | None:
    """Detect a single move from occupancy before/after snapshots."""
    departed, arrived = _departed_arrived(previous_cells, current_cells)
    arrived = _filter_arrived_by_legal_moves(departed, arrived, fen)

    if len(departed) == 2 and len(arrived) == 1:
        paired = _pair_capture_move(departed, arrived, fen)
    else:
        paired = _pair_departed_arrived(departed, arrived)
    if paired is not None:
        from_sq, to_sq = paired
        return DiffMoveResult(
            from_square=from_sq,
            to_square=to_sq,
            departed=departed,
            arrived=arrived,
            confident=True,
            via_inference=False,
        )

    if len(arrived) == 1 and len(departed) == 0:
        to_sq = arrived[0]
        from_sq = _infer_from_square(previous_cells, to_sq, fen)
        if from_sq:
            return DiffMoveResult(
                from_square=from_sq,
                to_square=to_sq,
                departed=departed,
                arrived=arrived,
                confident=True,
                via_inference=True,
            )

    if len(departed) == 2 and len(arrived) == 0:
        paired = _pair_two_departed_capture(departed, fen)
        if paired is not None:
            from_sq, to_sq = paired
            return DiffMoveResult(
                from_square=from_sq,
                to_square=to_sq,
                departed=departed,
                arrived=arrived,
                confident=True,
                via_inference=True,
            )

    if len(departed) == 1 and len(arrived) == 0:
        from_sq = departed[0]
        to_sq = _legal_destination_for_departed(from_sq, current_cells, previous_cells, fen)
        if to_sq is None:
            to_sq = _infer_to_square(previous_cells, current_cells, from_sq, fen)
        if to_sq:
            return DiffMoveResult(
                from_square=from_sq,
                to_square=to_sq,
                departed=departed,
                arrived=arrived,
                confident=True,
                via_inference=True,
            )

    if len(departed) >= 1 and len(arrived) >= 1:
        paired = _pair_departed_arrived(departed, arrived)
        if paired is not None:
            from_sq, to_sq = paired
            return DiffMoveResult(
                from_square=from_sq,
                to_square=to_sq,
                departed=departed,
                arrived=arrived,
                confident=True,
                via_inference=True,
            )

    return None
