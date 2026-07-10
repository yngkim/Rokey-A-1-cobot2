"""Orchestrate side-view capture and recorded-board diff (no RealSense)."""

from __future__ import annotations

from chess_web_ui.board_twin.comparator import compare_board_states
from chess_web_ui.board_twin.side_service import BoardTwinSideService, SideServiceConfig
from chess_web_ui.board_twin.suggestions import build_recovery_suggestions
from chess_web_ui.board_twin.types import BoardTwinVerifyResult, SideViewBoardEstimate


def run_board_twin_verify(
    *,
    recorded_fen: str,
    side_service: BoardTwinSideService | None,
    scan_message: str = '',
    confirm_failed: bool = False,
    side_estimate: SideViewBoardEstimate | None = None,
) -> BoardTwinVerifyResult:
    estimate = side_estimate
    side_message = ''
    if estimate is None and side_service is not None:
        estimate, side_message = side_service.detect_from_webcam(recorded_fen=recorded_fen)

    if estimate is None:
        return BoardTwinVerifyResult(
            success=False,
            aligned=False,
            message=side_message or '사이드뷰 추론에 실패했습니다',
            recorded_fen=recorded_fen,
            scan_message=scan_message or side_message,
        )

    mismatches = compare_board_states(
        recorded_fen=recorded_fen,
        side_estimate=estimate,
    )
    suggestions = build_recovery_suggestions(
        mismatches=mismatches,
        recorded_fen=recorded_fen,
        side_estimate=estimate,
        confirm_failed=confirm_failed,
    )
    aligned = len(mismatches) == 0
    if aligned:
        message = '기록 보드와 사이드뷰 추정이 일치합니다.'
    else:
        message = f'기록 보드와 사이드뷰 참고 차이 {len(mismatches)}건이 있습니다.'
        if suggestions:
            message = f'{message} {suggestions[0].message}'

    return BoardTwinVerifyResult(
        success=True,
        aligned=aligned,
        message=message,
        recorded_fen=recorded_fen,
        side_estimate=estimate,
        realsense_occupancy=None,
        mismatches=mismatches,
        suggestions=suggestions,
        scan_message=scan_message or side_message,
    )


def build_side_service_from_paths(
    *,
    model_path: str,
    calibration_path: str,
    conf_threshold: float = 0.15,
    iou_threshold: float = 0.5,
    imgsz: int = 640,
    device: str = '',
    webcam_fps: int = 30,
) -> BoardTwinSideService:
    return BoardTwinSideService(
        SideServiceConfig(
            model_path=model_path,
            calibration_path=calibration_path,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            imgsz=imgsz,
            device=device,
            webcam_fps=webcam_fps,
        )
    )
