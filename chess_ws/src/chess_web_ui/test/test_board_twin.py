"""Tests for board twin normalization and comparison."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_game.board_utils import occupancy_from_fen
from chess_web_ui.board_twin.calibration import SideViewSquareMapper
from chess_web_ui.board_twin.comparator import compare_board_states, occupancy_diff_squares
from chess_web_ui.board_twin.engine import run_board_twin_verify
from chess_web_ui.board_twin.normalizer import (
    class_name_to_symbol,
    normalize_side_detections,
    piece_map_to_placement_fen,
)
from chess_web_ui.board_twin.paths import resolve_side_model_path
from chess_web_ui.board_twin.side_service import annotate_with_squares
from chess_web_ui.board_twin.suggestions import build_recovery_suggestions
from chess_web_ui.board_twin.types import SideDetectionView, SideViewBoardEstimate


@dataclass
class _Det:
    class_name: str
    center: tuple[float, float]
    score: float
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def _mapper() -> SideViewSquareMapper:
    return SideViewSquareMapper(
        corners=[(0, 0), (800, 0), (800, 800), (0, 800)],
        flip_files=False,
        board_flipped=False,
    )


def test_class_name_to_symbol() -> None:
    assert class_name_to_symbol('white-pawn') == 'P'
    assert class_name_to_symbol('black-knight') == 'n'
    assert class_name_to_symbol('white_pawn') == 'P'
    assert class_name_to_symbol('black_knight') == 'n'


def test_normalize_side_detections_maps_center_to_square() -> None:
    detections = [
        _Det('white-pawn', (50, 50), 0.9, bbox=(40.0, 40.0, 60.0, 60.0)),
        _Det('white-pawn', (150, 50), 0.8, bbox=(140.0, 40.0, 160.0, 60.0)),
    ]
    estimate = normalize_side_detections(detections, _mapper(), recorded_fen=START_FEN)
    assert 'a1' in estimate.piece_map
    assert estimate.piece_map['a1'] == 'P'
    assert estimate.occupancy[0] is True
    assert estimate.detections[0].bbox == (40.0, 40.0, 60.0, 60.0)


def test_annotate_with_squares_draws_on_frame() -> None:
    import numpy as np

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    views = [
        SideDetectionView(
            class_name='white-pawn',
            symbol='P',
            square='e2',
            confidence=0.91,
            center_x=50.0,
            center_y=50.0,
            bbox=(40.0, 40.0, 60.0, 60.0),
        )
    ]
    annotated = annotate_with_squares(frame, views)
    assert annotated.shape == frame.shape
    assert not np.array_equal(annotated, frame)


def test_resolve_side_model_path_prefers_local_weights(tmp_path) -> None:
    resolved = resolve_side_model_path('yamero999/chess-piece-detection-yolo11n')
    assert resolved.endswith('chess_final_side1_best.pt')
    custom = tmp_path / 'custom.pt'
    custom.write_bytes(b'fake')
    explicit = resolve_side_model_path(str(custom))
    assert explicit == str(custom.resolve())


def test_compare_recorded_vs_sideview_occupancy_diff() -> None:
    side_occ = list(occupancy_from_fen(START_FEN))
    side_occ[chess.parse_square('e2')] = False
    side_estimate = SideViewBoardEstimate(
        piece_map={},
        occupancy=side_occ,
        placement_fen=piece_map_to_placement_fen({}),
    )
    mismatches = compare_board_states(
        recorded_fen=START_FEN,
        side_estimate=side_estimate,
    )
    assert any(item.square == 'e2' for item in mismatches)
    assert all(not item.authoritative for item in mismatches)


def test_compare_aligned_when_sideview_matches_recorded() -> None:
    board = chess.Board(START_FEN)
    piece_map = {
        chess.square_name(sq): board.piece_at(sq).symbol()
        for sq in chess.SQUARES
        if board.piece_at(sq) is not None
    }
    side_estimate = SideViewBoardEstimate(
        piece_map=piece_map,
        occupancy=occupancy_from_fen(START_FEN),
        placement_fen=board.board_fen(),
    )
    mismatches = compare_board_states(
        recorded_fen=START_FEN,
        side_estimate=side_estimate,
    )
    assert mismatches == []


def test_suggestions_for_sideview_mismatch() -> None:
    side_occ = list(occupancy_from_fen(START_FEN))
    side_occ[chess.parse_square('e2')] = False
    side_estimate = SideViewBoardEstimate(
        piece_map={},
        occupancy=side_occ,
        placement_fen=piece_map_to_placement_fen({}),
    )
    mismatches = compare_board_states(
        recorded_fen=START_FEN,
        side_estimate=side_estimate,
    )
    suggestions = build_recovery_suggestions(
        mismatches=mismatches,
        recorded_fen=START_FEN,
        side_estimate=side_estimate,
        confirm_failed=True,
    )
    kinds = {item.kind for item in suggestions}
    assert 'confirm_player_move_recommended' in kinds
    assert 'rescan_recommended' in kinds


def test_engine_sideview_only() -> None:
    board = chess.Board(START_FEN)
    piece_map = {
        chess.square_name(sq): board.piece_at(sq).symbol()
        for sq in chess.SQUARES
        if board.piece_at(sq) is not None
    }
    side_estimate = SideViewBoardEstimate(
        piece_map=piece_map,
        occupancy=occupancy_from_fen(START_FEN),
        placement_fen=board.board_fen(),
    )
    result = run_board_twin_verify(
        recorded_fen=START_FEN,
        side_service=None,
        side_estimate=side_estimate,
    )
    assert result.success is True
    assert result.aligned is True


def test_occupancy_diff_squares() -> None:
    recorded = [False] * 64
    side = [False] * 64
    recorded[chess.parse_square('e2')] = True
    side[chess.parse_square('e4')] = True
    diff = occupancy_diff_squares(recorded, side)
    assert set(diff) == {'e2', 'e4'}
