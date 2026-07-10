"""Compare recorded FEN with side-view estimate (reference only; no RealSense)."""

from __future__ import annotations

from chess_game.board_utils import index_to_square_name, occupancy_from_fen
from chess_web_ui.board_twin.normalizer import recorded_piece_map
from chess_web_ui.board_twin.types import SideViewBoardEstimate, TwinMismatch


def compare_board_states(
    *,
    recorded_fen: str,
    side_estimate: SideViewBoardEstimate | None,
) -> list[TwinMismatch]:
    if side_estimate is None:
        return []
    return _compare_recorded_vs_sideview(recorded_fen, side_estimate)


def occupancy_diff_squares(
    recorded_occ: list[bool],
    sideview_occ: list[bool],
) -> list[str]:
    """Squares where recorded board and side-view occupancy disagree."""
    squares: list[str] = []
    for idx in range(64):
        recorded_has = recorded_occ[idx] if idx < len(recorded_occ) else False
        sv_has = sideview_occ[idx] if idx < len(sideview_occ) else False
        if recorded_has != sv_has:
            squares.append(index_to_square_name(idx))
    return squares


def authoritative_mismatches(mismatches: list[TwinMismatch]) -> list[TwinMismatch]:
    return [item for item in mismatches if item.authoritative]


def _compare_recorded_vs_sideview(
    recorded_fen: str,
    side_estimate: SideViewBoardEstimate,
) -> list[TwinMismatch]:
    recorded_map = recorded_piece_map(recorded_fen)
    recorded_occ = occupancy_from_fen(recorded_fen)
    side_map = side_estimate.piece_map
    side_occ = side_estimate.occupancy
    out: list[TwinMismatch] = []

    for idx in range(64):
        square = index_to_square_name(idx)
        recorded_has = recorded_occ[idx]
        sv_has = side_occ[idx] if idx < len(side_occ) else False
        recorded_symbol = recorded_map.get(square, '')
        sv_symbol = side_map.get(square, '')

        if recorded_has == sv_has and (not recorded_symbol or not sv_symbol or recorded_symbol == sv_symbol):
            continue

        if recorded_has and not sv_has:
            msg = (
                f'{square}({recorded_symbol or "?"})는 기록에 있으나 '
                f'사이드뷰에서 미감지되었습니다 (참고용)'
            )
        elif not recorded_has and sv_has:
            msg = (
                f'{square}는 기록에 비어 있으나 '
                f'사이드뷰에서 {sv_symbol or "기물"} 감지 (참고용)'
            )
        elif recorded_symbol and sv_symbol and recorded_symbol != sv_symbol:
            msg = (
                f'{square} 기물 종류 차이: 기록 {recorded_symbol}, '
                f'사이드뷰 {sv_symbol} (참고용)'
            )
        else:
            continue

        out.append(
            TwinMismatch(
                kind='sideview_reference_disagreement',
                square=square,
                message=msg,
                recorded_symbol=recorded_symbol,
                actual_symbol=sv_symbol,
                evidence='sideview',
                authoritative=False,
            )
        )
    return out
