"""Vision-driven chess game session state (occupancy diff + FEN)."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_game.board_utils import index_to_square_name, occupancy_from_fen, sanitize_depth_cells
from chess_game.game_state import GameState
from chess_game.move_matcher import MoveMatcher
from chess_game.move_resolve import promotion_notice, promotion_piece_char, resolve_legal_uci, resolve_legal_uci_full
from chess_game.occupancy_diff import (
    castling_diff_pattern,
    detect_move_from_diff,
    infer_captured_piece,
)

try:
    from chess_web_ui.agent_debug_log import agent_log
except ImportError:
    def agent_log(*_args, **_kwargs) -> None:
        pass


def _departed_arrived(
    baseline: list[bool],
    filtered: list[bool],
) -> tuple[list[str], list[str]]:
    departed: list[str] = []
    arrived: list[str] = []
    for idx, (prev, curr) in enumerate(zip(baseline, filtered)):
        if prev and not curr:
            departed.append(index_to_square_name(idx))
        elif not prev and curr:
            arrived.append(index_to_square_name(idx))
    return departed, arrived


def _no_move_outcome(
    *,
    baseline: list[bool],
    filtered: list[bool],
    fen_before: str,
    departed: list[str],
    arrived: list[str],
) -> ScanOutcome:
    return ScanOutcome(
        success=False,
        message=(
            f'no move detected; departed={departed or "-"} arrived={arrived or "-"}'
        ),
        cells=list(filtered),
        fen=fen_before,
    )


def _prune_departed_noise(
    departed: list[str],
    arrived: list[str],
    fen: str,
    current_cells: list[bool] | None = None,
) -> list[str]:
    """Drop stale depth ghosts (e.g. a2) when a real from→to move is visible."""
    if not departed:
        return departed
    if len(arrived) == 1:
        to_sq = arrived[0]
        legal_from = [
            from_sq
            for from_sq in departed
            if resolve_legal_uci_full(f'{from_sq}{to_sq}', fen) is not None
        ]
        if len(legal_from) == 1:
            return legal_from
    if len(departed) == 1 and not arrived:
        try:
            from_square = chess.parse_square(departed[0])
        except ValueError:
            return departed
        board = chess.Board(fen)
        if board.piece_at(from_square) is None:
            return departed
        if current_cells is not None:
            # A capture onto a square that is occupied both before and after
            # (piece taken, capturer arrives) never shows up as "arrived" — it's
            # a real move, not a depth-sensor ghost. Only prune when no legal
            # move from here still explains the diff.
            has_legal_destination = any(
                move.from_square == from_square and current_cells[move.to_square]
                for move in board.legal_moves
            )
            if has_legal_destination:
                return departed
        return []
    return departed


def _has_minimum_move_evidence(
    departed: list[str],
    arrived: list[str],
    fen: str,
) -> bool:
    if len(departed) + len(arrived) == 0:
        return False
    if len(departed) == 2 and len(arrived) == 0:
        return castling_diff_pattern(departed, arrived, fen)
    if len(departed) == 1 and len(arrived) == 0:
        # A single-square capture (piece taken, capturer lands on the same
        # square) never produces an "arrived" signal, so it can only ever reach
        # this point with exactly one piece of evidence. By the time we get
        # here, _prune_departed_noise has already confirmed this departure
        # matches a real legal move rather than depth-sensor noise, so trust
        # it instead of demanding >=2 evidence points that no single-square
        # capture could ever satisfy.
        return True
    return len(departed) + len(arrived) >= 2


def _from_square_matches_turn(fen: str, from_sq: str) -> bool:
    board = chess.Board(fen)
    try:
        square = chess.parse_square(from_sq)
    except ValueError:
        return False
    piece = board.piece_at(square)
    if piece is None:
        return False
    return piece.color == board.turn


@dataclass
class ScanOutcome:
    success: bool
    message: str
    cells: list[bool] | None = None
    from_square: str = ''
    to_square: str = ''
    captured_piece: str = ''
    fen: str = ''
    fen_before: str = ''
    uci: str = ''
    promotion_piece: str = ''
    promotion_required: bool = False


class VisionSession:
    def __init__(self) -> None:
        self.game = GameState()
        self.matcher = MoveMatcher()
        self.previous_cells: list[bool] | None = None
        self.scan_id = 0
        self.empty_square_min_conf = 0.42
        self.fen_snap_baseline = True

    def configure_depth_filter(self, *, empty_square_min_conf: float, fen_snap_baseline: bool) -> None:
        self.empty_square_min_conf = empty_square_min_conf
        self.fen_snap_baseline = fen_snap_baseline

    def _normalize_confidence(self, cells: list[bool], confidence: list[float] | None) -> list[float]:
        if confidence and len(confidence) == 64:
            return list(confidence)
        return [1.0 if occupied else 0.0 for occupied in cells]

    def _filter_cells(self, cells: list[bool], confidence: list[float], fen: str) -> list[bool]:
        return sanitize_depth_cells(
            cells,
            confidence,
            fen,
            empty_square_min_conf=self.empty_square_min_conf,
        )

    def _commit_baseline(self, cells: list[bool] | None) -> None:
        if self.fen_snap_baseline:
            self.previous_cells = occupancy_from_fen(self.game.fen)
        elif cells is not None:
            self.previous_cells = list(cells)

    def _promotion_candidates(self, fen_before: str, from_sq: str, to_sq: str) -> list[str]:
        board = chess.Board(fen_before)
        try:
            from_square = chess.parse_square(from_sq)
            to_square = chess.parse_square(to_sq)
        except ValueError:
            return []
        return [
            move.uci()
            for move in board.legal_moves
            if move.from_square == from_square
            and move.to_square == to_square
            and move.promotion is not None
        ]

    def _resolve_and_apply(
        self,
        fen_before: str,
        from_sq: str,
        to_sq: str,
        *,
        baseline: list[bool],
        filtered: list[bool],
        promotion: str = '',
    ) -> ScanOutcome | None:
        if not _from_square_matches_turn(fen_before, from_sq):
            return None
        if promotion:
            from chess_game.move_resolve import resolve_legal_uci_full

            uci = resolve_legal_uci_full(f'{from_sq}{to_sq}{promotion}', fen_before)
            if uci is None:
                return None
        else:
            uci = resolve_legal_uci(fen_before, from_sq, to_sq)
            if uci is None:
                promos = self._promotion_candidates(fen_before, from_sq, to_sq)
                if promos:
                    return ScanOutcome(
                        success=False,
                        message='promotion_required',
                        promotion_required=True,
                        cells=list(filtered),
                        from_square=from_sq,
                        to_square=to_sq,
                        uci=f'{from_sq}{to_sq}',
                        fen=fen_before,
                    )
                if not _from_square_matches_turn(fen_before, from_sq):
                    return None
                matcher_result = self.matcher.match_from_occupancy(fen_before, baseline, filtered)
                if matcher_result.matched and matcher_result.best:
                    uci = matcher_result.best
                    from_sq, to_sq = uci[:2], uci[2:4]
                else:
                    return None

        self.game.apply_uci(uci)
        move = chess.Move.from_uci(uci)
        promo = promotion_piece_char(move)
        captured = infer_captured_piece(fen_before, from_sq, to_sq)
        self._commit_baseline(filtered)
        capture_note = f' captured {captured}' if captured else ''
        promo_note = ''
        if promo:
            promo_note = f' ({promotion_notice(from_sq, to_sq, promo)})'
        return ScanOutcome(
            success=True,
            message=f'detected move {from_sq} -> {to_sq}{capture_note}{promo_note}',
            cells=list(filtered),
            from_square=from_sq,
            to_square=to_sq,
            captured_piece=captured,
            fen=self.game.fen,
            fen_before=fen_before,
            uci=uci,
            promotion_piece=promo,
        )

    def reset_game(self) -> None:
        self.game = GameState()
        self.previous_cells = None
        self.scan_id = 0

    def baseline_cells(self) -> list[bool]:
        if self.previous_cells is not None:
            return self.previous_cells
        return occupancy_from_fen(self.game.fen)

    def apply_initial_scan(self, cells: list[bool], confidence: list[float] | None = None) -> ScanOutcome:
        self.scan_id += 1
        conf = self._normalize_confidence(cells, confidence)
        filtered = self._filter_cells(cells, conf, self.game.fen)
        self.previous_cells = list(filtered)
        occupied = sum(filtered)
        return ScanOutcome(
            success=True,
            message=f'initial scan: {occupied} occupied squares',
            cells=list(filtered),
            fen=self.game.fen,
        )

    def apply_player_move_scan(self, cells: list[bool], confidence: list[float] | None = None) -> ScanOutcome:
        self.scan_id += 1
        conf = self._normalize_confidence(cells, confidence)
        baseline = self.baseline_cells()
        used_fen_baseline = self.previous_cells is None

        fen_before = self.game.fen
        filtered = self._filter_cells(cells, conf, fen_before)
        departed, arrived = _departed_arrived(baseline, filtered)
        departed = _prune_departed_noise(departed, arrived, fen_before, filtered)
        if filtered == baseline or not _has_minimum_move_evidence(departed, arrived, fen_before):
            agent_log(
                'vision_session.py:apply_player_move_scan',
                'no move evidence',
                {
                    'departed': departed,
                    'arrived': arrived,
                    'fen_before': fen_before,
                    'used_fen_baseline': used_fen_baseline,
                },
                hypothesis_id='D',
            )
            return _no_move_outcome(
                baseline=baseline,
                filtered=filtered,
                fen_before=fen_before,
                departed=departed,
                arrived=arrived,
            )

        diff = detect_move_from_diff(baseline, filtered, fen_before)
        if diff is not None and diff.confident and not diff.via_inference:
            if not _from_square_matches_turn(fen_before, diff.from_square):
                pass
            else:
                outcome = self._resolve_and_apply(
                    fen_before,
                    diff.from_square,
                    diff.to_square,
                    baseline=baseline,
                    filtered=filtered,
                )
                if outcome is not None:
                    baseline_note = ' (fen baseline)' if used_fen_baseline else ''
                    outcome.message = f'{outcome.message}{baseline_note}'
                    agent_log(
                        'vision_session.py:apply_player_move_scan',
                        'diff move ok',
                        {'uci': outcome.uci, 'fen_before': fen_before},
                        hypothesis_id='D',
                    )
                    return outcome
                if self._promotion_candidates(fen_before, diff.from_square, diff.to_square):
                    return ScanOutcome(
                        success=False,
                        message='promotion_required',
                        promotion_required=True,
                        cells=list(filtered),
                        from_square=diff.from_square,
                        to_square=diff.to_square,
                        uci=f'{diff.from_square}{diff.to_square}',
                        fen=fen_before,
                    )
                return ScanOutcome(
                    success=False,
                    message=f'illegal move: {diff.from_square}{diff.to_square}',
                    cells=list(filtered),
                    from_square=diff.from_square,
                    to_square=diff.to_square,
                    fen=fen_before,
                )

        result = self.matcher.match_from_occupancy(
            fen_before,
            baseline,
            filtered,
        )
        if result.matched and result.best:
            from_sq, to_sq = result.best[:2], result.best[2:4]
            if _from_square_matches_turn(fen_before, from_sq):
                outcome = self._resolve_and_apply(
                    fen_before,
                    from_sq,
                    to_sq,
                    baseline=baseline,
                    filtered=filtered,
                )
                if outcome is not None:
                    outcome.message = f'{outcome.message} (legal match)'
                    return outcome
            if self._promotion_candidates(fen_before, from_sq, to_sq):
                return ScanOutcome(
                    success=False,
                    message='promotion_required',
                    promotion_required=True,
                    cells=list(filtered),
                    from_square=from_sq,
                    to_square=to_sq,
                    uci=f'{from_sq}{to_sq}',
                    fen=fen_before,
                )

        if result.candidates:
            joined = ', '.join(result.candidates[:5])
            suffix = ' ...' if len(result.candidates) > 5 else ''
            return ScanOutcome(
                success=False,
                message=f'ambiguous move; candidates: {joined}{suffix}',
                cells=list(cells),
                fen=fen_before,
            )

        return _no_move_outcome(
            baseline=baseline,
            filtered=filtered,
            fen_before=fen_before,
            departed=departed,
            arrived=arrived,
        )

    def set_board_from_fen(self, fen: str) -> ScanOutcome:
        try:
            chess.Board(fen)
        except ValueError as exc:
            return ScanOutcome(success=False, message=f'invalid FEN: {exc}')

        self.game = GameState(fen)
        self.previous_cells = occupancy_from_fen(fen)
        self.scan_id += 1
        return ScanOutcome(
            success=True,
            message='board corrected manually',
            cells=list(self.previous_cells),
            fen=self.game.fen,
        )

    def apply_player_promotion(self, from_sq: str, to_sq: str, promotion: str) -> ScanOutcome:
        from chess_game.move_resolve import resolve_legal_uci_full

        fen_before = self.game.fen
        uci = resolve_legal_uci_full(f'{from_sq}{to_sq}{promotion}', fen_before)
        if uci is None:
            return ScanOutcome(
                success=False,
                message=f'illegal promotion: {from_sq}{to_sq}{promotion}',
                fen=fen_before,
            )
        self.game.apply_uci(uci)
        move = chess.Move.from_uci(uci)
        promo = promotion_piece_char(move)
        self.previous_cells = occupancy_from_fen(self.game.fen)
        self.scan_id += 1
        promo_note = f' ({promotion_notice(from_sq, to_sq, promo)})' if promo else ''
        return ScanOutcome(
            success=True,
            message=f'detected move {from_sq} -> {to_sq}{promo_note}',
            cells=list(self.previous_cells),
            from_square=from_sq,
            to_square=to_sq,
            fen=self.game.fen,
            uci=uci,
            promotion_piece=promo,
        )

    def apply_robot_move(
        self,
        from_col: int,
        from_row: int,
        to_col: int,
        to_row: int,
        *,
        promotion: str = '',
        uci: str = '',
    ) -> ScanOutcome:
        from_name = chess.square_name(chess.square(from_col, from_row))
        to_name = chess.square_name(chess.square(to_col, to_row))
        full_uci = uci.strip()
        if not full_uci:
            full_uci = f'{from_name}{to_name}{promotion}'

        resolved = resolve_legal_uci(
            self.game.fen,
            from_name,
            to_name,
            promotion=_promotion_type(promotion) if promotion else None,
        )
        if resolved is None and full_uci:
            from chess_game.move_resolve import resolve_legal_uci_full

            resolved = resolve_legal_uci_full(full_uci, self.game.fen)
        if resolved is None:
            return ScanOutcome(
                success=False,
                message=f'invalid robot move: {full_uci}',
            )

        board = chess.Board(self.game.fen)
        try:
            board.push_uci(resolved)
        except ValueError as exc:
            return ScanOutcome(success=False, message=f'invalid robot move: {exc}')

        self.game.apply_uci(resolved)
        move = chess.Move.from_uci(resolved)
        promo = promotion_piece_char(move)
        self.previous_cells = occupancy_from_fen(self.game.fen)

        self.scan_id += 1
        promo_note = ''
        if promo:
            promo_note = f' ({promotion_notice(from_name, to_name, promo)})'
        return ScanOutcome(
            success=True,
            message=f'robot move applied {from_name} -> {to_name}{promo_note}',
            cells=list(self.previous_cells) if self.previous_cells is not None else None,
            from_square=from_name,
            to_square=to_name,
            fen=self.game.fen,
            uci=resolved,
            promotion_piece=promo,
        )


def _promotion_type(promotion: str) -> chess.PieceType | None:
    promo_map = {'q': chess.QUEEN, 'r': chess.ROOK, 'b': chess.BISHOP, 'n': chess.KNIGHT}
    return promo_map.get(promotion.strip().lower())
