"""Advisory recovery suggestions from side-view vs recorded board."""

from __future__ import annotations

from chess_web_ui.board_twin.types import SideViewBoardEstimate, TwinMismatch, TwinSuggestion


def build_recovery_suggestions(
    *,
    mismatches: list[TwinMismatch],
    recorded_fen: str,
    side_estimate: SideViewBoardEstimate | None,
    confirm_failed: bool = False,
) -> list[TwinSuggestion]:
    if not mismatches:
        return [
            TwinSuggestion(
                kind='no_action_needed',
                message='기록 보드와 사이드뷰 추정이 일치합니다.',
                priority=0,
            )
        ]

    suggestions: list[TwinSuggestion] = []
    diff_count = len(mismatches)

    if confirm_failed:
        suggestions.append(
            TwinSuggestion(
                kind='confirm_player_move_recommended',
                message='수 확인이 실패했습니다. 보드를 다시 확인한 뒤 수 두었음을 다시 시도하세요.',
                priority=20,
            )
        )

    suggestions.append(
        TwinSuggestion(
            kind='rescan_recommended',
            message=(
                f'사이드뷰 참고 차이 {diff_count}건입니다. '
                'RealSense 수 확인 흐름과 보드 상태를 직접 확인하세요.'
            ),
            priority=30,
        )
    )

    if side_estimate is not None and side_estimate.placement_fen:
        suggestions.append(
            TwinSuggestion(
                kind='correct_board_candidate_fen',
                message=(
                    '사이드뷰 추정 배치 참고 FEN입니다. '
                    '정확도가 낮을 수 있으니 적용 전 반드시 확인하세요.'
                ),
                candidate_fen=side_estimate.placement_fen,
                priority=10,
            )
        )

    suggestions.sort(key=lambda item: item.priority, reverse=True)
    return suggestions
