"""Vision-driven chess game session state (occupancy diff + FEN)."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_game.board_utils import index_to_square_name, occupancy_from_fen
from chess_game.game_state import GameState
from chess_game.move_matcher import MoveMatcher
from chess_game.occupancy_diff import detect_move_from_diff, infer_captured_piece


@dataclass
class ScanOutcome:
    success: bool
    message: str
    cells: list[bool] | None = None
    from_square: str = ''
    to_square: str = ''
    captured_piece: str = ''
    fen: str = ''


class VisionSession:
    def __init__(self) -> None:
        self.game = GameState()
        self.matcher = MoveMatcher()
        self.previous_cells: list[bool] | None = None
        self.scan_id = 0

    def reset_game(self) -> None:
        self.game = GameState()
        self.previous_cells = None
        self.scan_id = 0

    def baseline_cells(self) -> list[bool]:
        if self.previous_cells is not None:
            return self.previous_cells
        return occupancy_from_fen(self.game.fen)

    def apply_initial_scan(self, cells: list[bool]) -> ScanOutcome:
        self.scan_id += 1
        self.previous_cells = list(cells)
        occupied = sum(cells)
        return ScanOutcome(
            success=True,
            message=f'initial scan: {occupied} occupied squares',
            cells=list(cells),
            fen=self.game.fen,
        )

    def apply_player_move_scan(self, cells: list[bool]) -> ScanOutcome:
        self.scan_id += 1
        baseline = self.baseline_cells()
        used_fen_baseline = self.previous_cells is None

        fen_before = self.game.fen
        diff = detect_move_from_diff(baseline, cells, fen_before)
        if diff is not None and diff.confident:
            from_sq = diff.from_square
            to_sq = diff.to_square
            uci = f'{from_sq}{to_sq}'
            captured = infer_captured_piece(
                fen_before,
                from_sq,
                to_sq,
                departed=diff.departed,
                baseline=baseline,
            )
            legal_note = ''
            applied = False
            try:
                board = chess.Board(fen_before)
                move = chess.Move.from_uci(uci)
                if move in board.legal_moves:
                    self.game.apply_uci(uci)
                    applied = True
            except ValueError:
                applied = False

            if not applied:
                if self.game.apply_vision_move(from_sq, to_sq):
                    legal_note = ' (vision board updated)'
                else:
                    legal_note = ' (occupancy only; board not updated)'

            self.previous_cells = list(cells)
            inference = ' inferred' if diff.via_inference else ''
            baseline_note = ' (fen baseline)' if used_fen_baseline else ''
            capture_note = f' captured {captured}' if captured else ''
            return ScanOutcome(
                success=True,
                message=(
                    f'detected move {from_sq} -> {to_sq}{capture_note}'
                    f'{inference}{legal_note}{baseline_note}'
                ),
                cells=list(cells),
                from_square=from_sq,
                to_square=to_sq,
                captured_piece=captured,
                fen=self.game.fen,
            )

        result = self.matcher.match_from_occupancy(
            fen_before,
            baseline,
            cells,
        )
        if result.matched and result.best:
            uci = result.best
            from_sq, to_sq = uci[:2], uci[2:4]
            captured = infer_captured_piece(fen_before, from_sq, to_sq)
            self.game.apply_uci(uci)
            self.previous_cells = list(cells)
            capture_note = f' captured {captured}' if captured else ''
            return ScanOutcome(
                success=True,
                message=f'detected move {from_sq} -> {to_sq}{capture_note} (legal match)',
                cells=list(cells),
                from_square=from_sq,
                to_square=to_sq,
                captured_piece=captured,
                fen=self.game.fen,
            )

        if result.candidates:
            joined = ', '.join(result.candidates[:5])
            suffix = ' ...' if len(result.candidates) > 5 else ''
            return ScanOutcome(
                success=False,
                message=f'ambiguous move; candidates: {joined}{suffix}',
                cells=list(cells),
                fen=self.game.fen,
            )

        departed, arrived = [], []
        for idx, (prev, curr) in enumerate(zip(baseline, cells)):
            if prev and not curr:
                departed.append(index_to_square_name(idx))
            elif not prev and curr:
                arrived.append(index_to_square_name(idx))

        return ScanOutcome(
            success=False,
            message=(
                f'no move detected; departed={departed or "-"} arrived={arrived or "-"}'
            ),
            cells=list(cells),
            fen=self.game.fen,
        )

    def apply_robot_move(self, from_col: int, from_row: int, to_col: int, to_row: int) -> ScanOutcome:
        from_name = chess.square_name(chess.square(from_col, from_row))
        to_name = chess.square_name(chess.square(to_col, to_row))
        uci = f'{from_name}{to_name}'

        board = chess.Board(self.game.fen)
        try:
            board.push_uci(uci)
        except ValueError as exc:
            return ScanOutcome(success=False, message=f'invalid robot move: {exc}')

        self.game.apply_uci(uci)
        from_idx = from_row * 8 + from_col
        to_idx = to_row * 8 + to_col
        if self.previous_cells is not None:
            cells = list(self.previous_cells)
            cells[from_idx] = False
            cells[to_idx] = True
            self.previous_cells = cells
        else:
            self.previous_cells = occupancy_from_fen(self.game.fen)

        self.scan_id += 1
        return ScanOutcome(
            success=True,
            message=f'robot move applied {from_name} -> {to_name}',
            cells=list(self.previous_cells) if self.previous_cells is not None else None,
            from_square=from_name,
            to_square=to_name,
            fen=self.game.fen,
        )
