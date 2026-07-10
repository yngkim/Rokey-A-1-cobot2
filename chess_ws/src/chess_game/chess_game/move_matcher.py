"""Match occupancy diffs to legal chess moves."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_game.board_utils import index_to_square_name, square_name_to_index
from chess_game.move_resolve import (
    DEFAULT_PROMOTION,
    relevant_changed_squares,
    resolve_legal_uci,
)


@dataclass
class MoveMatchResult:
    candidates: list[str]
    ambiguous: bool
    matched: bool

    @property
    def best(self) -> str | None:
        if len(self.candidates) == 1:
            return self.candidates[0]
        return None


def _pick_promotion_candidate(candidates: list[str]) -> list[str]:
    if len(candidates) <= 1:
        return candidates
    if all(candidate[:4] == candidates[0][:4] for candidate in candidates):
        queen = [candidate for candidate in candidates if candidate.endswith('q')]
        if len(queen) == 1:
            return queen
    return candidates


class MoveMatcher:
    def match_from_occupancy(
        self,
        fen: str,
        previous_cells: list[bool],
        current_cells: list[bool],
    ) -> MoveMatchResult:
        board = chess.Board(fen)
        changed = [
            idx for idx, (prev, curr) in enumerate(zip(previous_cells, current_cells))
            if prev != curr
        ]
        changed_names = {index_to_square_name(idx) for idx in changed}
        if not changed_names:
            return MoveMatchResult(candidates=[], ambiguous=False, matched=False)

        candidates: list[str] = []
        for move in board.legal_moves:
            if self._move_matches_changed_squares(board, move, changed_names):
                candidates.append(move.uci())

        candidates = _pick_promotion_candidate(candidates)
        if len(candidates) == 1:
            return MoveMatchResult(
                candidates=candidates,
                ambiguous=False,
                matched=True,
            )

        if candidates:
            return MoveMatchResult(
                candidates=candidates,
                ambiguous=len(candidates) > 1,
                matched=False,
            )

        scored = self._score_legal_moves(board, previous_cells, current_cells, changed_names)
        if not scored:
            return MoveMatchResult(candidates=[], ambiguous=False, matched=False)

        best_score = scored[0][0]
        top = [uci for score, uci in scored if score == best_score]
        top = _pick_promotion_candidate(top)
        if len(top) == 1 and best_score >= 6:
            return MoveMatchResult(candidates=top, ambiguous=False, matched=True)

        return MoveMatchResult(
            candidates=top,
            ambiguous=len(top) > 1,
            matched=False,
        )

    def _score_legal_moves(
        self,
        board: chess.Board,
        previous_cells: list[bool],
        current_cells: list[bool],
        changed_names: set[str],
    ) -> list[tuple[int, str]]:
        if not changed_names:
            return []
        scored: list[tuple[int, str]] = []
        for move in board.legal_moves:
            score = self._score_move(board, move, previous_cells, current_cells)
            if score > 0:
                scored.append((score, move.uci()))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored

    def _score_move(
        self,
        board: chess.Board,
        move: chess.Move,
        previous_cells: list[bool],
        current_cells: list[bool],
    ) -> int:
        score = 0
        from_idx = square_name_to_index(chess.square_name(move.from_square))
        to_idx = square_name_to_index(chess.square_name(move.to_square))

        if previous_cells[from_idx] and not current_cells[from_idx]:
            score += 3
        elif previous_cells[from_idx] != current_cells[from_idx]:
            score += 1

        if not previous_cells[to_idx] and current_cells[to_idx]:
            score += 3
        elif previous_cells[to_idx] != current_cells[to_idx]:
            score += 1

        if board.is_capture(move):
            cap_idx = square_name_to_index(chess.square_name(move.to_square))
            if previous_cells[cap_idx] and current_cells[cap_idx]:
                score += 4
            elif previous_cells[cap_idx] and not current_cells[cap_idx]:
                score += 2

        if board.is_en_passant(move):
            cap_sq = move.to_square + (-8 if board.turn == chess.WHITE else 8)
            cap_idx = square_name_to_index(chess.square_name(cap_sq))
            if previous_cells[cap_idx] and not current_cells[cap_idx]:
                score += 4

        if board.is_castling(move):
            score += 6

        for name in relevant_changed_squares(board, move):
            idx = square_name_to_index(name)
            if previous_cells[idx] and not current_cells[idx]:
                score += 2
            elif not previous_cells[idx] and current_cells[idx]:
                score += 2

        return score

    def _move_matches_changed_squares(
        self,
        board: chess.Board,
        move: chess.Move,
        changed_names: set[str],
    ) -> bool:
        from_sq = chess.square_name(move.from_square)
        to_sq = chess.square_name(move.to_square)
        if board.is_castling(move):
            return from_sq in changed_names and to_sq in changed_names
        return relevant_changed_squares(board, move).issubset(changed_names)

    def resolve_from_squares(
        self,
        fen: str,
        from_sq: str,
        to_sq: str,
        *,
        promotion: chess.PieceType | None = None,
    ) -> str | None:
        return resolve_legal_uci(
            fen,
            from_sq,
            to_sq,
            promotion=promotion or DEFAULT_PROMOTION,
        )
