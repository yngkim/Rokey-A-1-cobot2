"""Match occupancy diffs to legal chess moves."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_game.board_utils import index_to_square_name, square_name_to_index


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

        candidates: list[str] = []
        for move in board.legal_moves:
            if self._move_matches_changed_squares(move, changed_names):
                candidates.append(move.uci())

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

        scored = self._score_legal_moves(board, previous_cells, current_cells)
        if not scored:
            return MoveMatchResult(candidates=[], ambiguous=False, matched=False)

        best_score = scored[0][0]
        top = [uci for score, uci in scored if score == best_score]
        if len(top) == 1 and best_score >= 4:
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
    ) -> list[tuple[int, str]]:
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
            if previous_cells[cap_idx] and not current_cells[cap_idx]:
                score += 2

        uci4 = move.uci()[:4]
        if uci4 in {'e1g1', 'e1c1', 'e8g8', 'e8c8'}:
            rook_squares = {
                'e1g1': ('h1', 'f1'),
                'e1c1': ('a1', 'd1'),
                'e8g8': ('h8', 'f8'),
                'e8c8': ('a8', 'd8'),
            }[uci4]
            for name in rook_squares:
                idx = square_name_to_index(name)
                if previous_cells[idx] and not current_cells[idx]:
                    score += 2
                elif not previous_cells[idx] and current_cells[idx]:
                    score += 2

        return score

    def _move_matches_changed_squares(
        self,
        move: chess.Move,
        changed_names: set[str],
    ) -> bool:
        from_name = chess.square_name(move.from_square)
        to_name = chess.square_name(move.to_square)
        relevant = {from_name, to_name}

        if move.uci()[:4] in {'e1g1', 'e1c1', 'e8g8', 'e8c8'}:
            rook_squares = {
                'e1g1': ('h1', 'f1'),
                'e1c1': ('a1', 'd1'),
                'e8g8': ('h8', 'f8'),
                'e8c8': ('a8', 'd8'),
            }[move.uci()[:4]]
            relevant.update(rook_squares)

        return relevant.issubset(changed_names)
