"""Shared types for board twin verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MismatchKind = Literal[
    'missing_piece_on_board',
    'unexpected_piece_on_square',
    'piece_type_mismatch',
    'occupancy_agrees_but_piece_type_conflicts',
    'recorded_fen_likely_stale',
    'human_manual_interference_suspected',
    'realsense_occupancy_mismatch',
    'sideview_reference_disagreement',
]

SuggestionKind = Literal[
    'rescan_recommended',
    'confirm_player_move_recommended',
    'correct_board_candidate_fen',
    'graveyard_review_recommended',
    'recorded_fen_likely_stale',
    'no_action_needed',
]


@dataclass(frozen=True)
class SideDetectionView:
    class_name: str
    symbol: str
    square: str
    confidence: float
    center_x: float
    center_y: float
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class SideViewBoardEstimate:
    piece_map: dict[str, str]
    occupancy: list[bool]
    placement_fen: str
    detections: list[SideDetectionView] = field(default_factory=list)
    duplicate_squares: list[str] = field(default_factory=list)
    unmapped_detections: int = 0
    message: str = ''


@dataclass(frozen=True)
class TwinMismatch:
    kind: MismatchKind
    square: str
    message: str
    recorded_symbol: str = ''
    actual_symbol: str = ''
    evidence: str = ''
    authoritative: bool = True


@dataclass(frozen=True)
class TwinSuggestion:
    kind: SuggestionKind
    message: str
    candidate_fen: str = ''
    priority: int = 0


@dataclass
class BoardTwinVerifyResult:
    success: bool
    aligned: bool
    message: str
    recorded_fen: str
    side_estimate: SideViewBoardEstimate | None = None
    realsense_occupancy: list[bool] | None = None
    mismatches: list[TwinMismatch] = field(default_factory=list)
    suggestions: list[TwinSuggestion] = field(default_factory=list)
    scan_message: str = ''

    def to_payload(self) -> dict[str, Any]:
        side_payload: dict[str, Any] | None = None
        if self.side_estimate is not None:
            side_payload = {
                'piece_map': dict(self.side_estimate.piece_map),
                'occupancy': list(self.side_estimate.occupancy),
                'placement_fen': self.side_estimate.placement_fen,
                'duplicate_squares': list(self.side_estimate.duplicate_squares),
                'unmapped_detections': self.side_estimate.unmapped_detections,
                'message': self.side_estimate.message,
                'detections': [
                    {
                        'class_name': det.class_name,
                        'symbol': det.symbol,
                        'square': det.square,
                        'confidence': det.confidence,
                    }
                    for det in self.side_estimate.detections
                ],
            }
        return {
            'success': self.success,
            'aligned': self.aligned,
            'message': self.message,
            'recorded_fen': self.recorded_fen,
            'side_estimate': side_payload,
            'realsense_occupancy': (
                list(self.realsense_occupancy) if self.realsense_occupancy is not None else None
            ),
            'mismatches': [
                {
                    'kind': item.kind,
                    'square': item.square,
                    'message': item.message,
                    'recorded_symbol': item.recorded_symbol,
                    'actual_symbol': item.actual_symbol,
                    'evidence': item.evidence,
                    'authoritative': item.authoritative,
                }
                for item in self.mismatches
            ],
            'suggestions': [
                {
                    'kind': item.kind,
                    'message': item.message,
                    'candidate_fen': item.candidate_fen,
                    'priority': item.priority,
                }
                for item in self.suggestions
            ],
            'scan_message': self.scan_message,
        }
