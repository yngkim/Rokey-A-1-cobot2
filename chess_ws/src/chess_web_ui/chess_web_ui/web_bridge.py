#!/usr/bin/env python3
"""HTTP bridge between React UI and ROS2 pick-place node."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Literal

import chess
import cv2
import numpy as np
import rclpy
import uvicorn
from chess_game.board_utils import occupancy_from_fen
from chess_game.move_resolve import (
    captured_piece_symbol,
    game_outcome,
    move_physics_flags,
    promotion_notice,
    promotion_piece_char,
    resolve_legal_uci_full,
)
from chess_engine.stockfish_client import StockfishClient
from chess_web_ui.agent_debug_log import agent_log
from chess_web_ui.bot_banter import (
    Difficulty,
    get_bot_profile,
    greeting,
    react_to_bot_move,
    react_to_game_over,
    react_to_illegal_move,
    react_to_illegal_move_reverted,
    react_to_player_move,
    react_to_voice_ambiguous,
    react_to_voice_confirm_fail,
    react_to_voice_confirm_success,
    react_to_voice_empty,
    react_to_voice_illegal,
    react_to_voice_parse_error,
    react_to_voice_promotion_required,
    react_to_voice_resign_fail,
    react_to_voice_resign_success,
    react_to_voice_restore_fail,
    react_to_voice_restore_success,
    react_to_voice_success,
    react_to_voice_undo_fail,
    react_to_voice_undo_success,
)
from chess_web_ui.board_correct_utils import guard_correction_fen, infer_human_move_uci
from chess_web_ui.capture_utils import resolve_capture_symbol
from chess_web_ui.voice_game_parser import parse_game_voice_command
from chess_web_ui.voice_move_parser import (
    VoiceMoveParseError,
    VoiceMoveParseOk,
    parse_voice_command_with_meta,
    resolve_voice_move,
)
from chess_web_ui.voice_semantic_parser import validate_voice_move_intent
from chess_web_ui.game_store import START_FEN, GameRecord, GameStore
from chess_web_ui.graveyard_reconcile import reconcile_graveyards_with_fen
from chess_web_ui.graveyard_utils import (
    graveyard_slot_index,
    human_graveyard_side,
    place_in_graveyard,
    robot_graveyard_side,
)
from chess_msgs.action import ExecuteMove, RestoreBoard
from chess_msgs.msg import BoardState, ChessMove, GameSnapshot, Square
from chess_msgs.srv import (
    ApplyRobotMove,
    ConfirmPlayerMove,
    ResetBoard,
    ScanInitial,
    SetBoard,
    UndoMoves,
)
from chess_web_ui.board_twin.calibration import SideViewCalibration
from chess_web_ui.board_twin.hand_presence import HandPresenceUpdate
from chess_web_ui.board_twin.hand_service import HandDetectorService, HandServiceConfig
from chess_web_ui.board_twin.side_service import draw_calibration_overlay
from chess_web_ui.board_twin.engine import build_side_service_from_paths, run_board_twin_verify
from chess_web_ui.board_twin.comparator import occupancy_diff_squares
from chess_web_ui.board_twin.paths import (
    default_hand_model_path,
    default_side_model_path,
    resolve_side_model_path,
)
from chess_web_ui.undo_utils import (
    build_undo_moves_payload,
    find_graveyard_slot_for_symbol,
    make_ply_snapshot,
)
from cv_bridge import CvBridge
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import Image
from std_msgs.msg import Bool
from std_srvs.srv import Trigger

BotStatus = Literal['idle', 'thinking', 'moving', 'paused', 'stopped', 'error']


class MoveRequest(BaseModel):
    from_square: str = Field(alias='from')
    to: str

    model_config = {'populate_by_name': True}


class GameConfigRequest(BaseModel):
    human_color: str
    difficulty: str = 'medium'
    board_orientation: str = 'standard'
    hand_auto_confirm_enabled: bool | None = None


class HandConfigRequest(BaseModel):
    auto_confirm_enabled: bool | None = None
    safety_enabled: bool | None = None


class BoardCorrectRequest(BaseModel):
    fen: str
    graveyard_slots: list[str | None] | None = None
    human_graveyard_slots: list[str | None] | None = None


class PromotionRequest(BaseModel):
    piece: str


class RevertIllegalMoveRequest(BaseModel):
    from_square: str = Field(alias='from')
    to: str

    model_config = {'populate_by_name': True}


class VoiceMoveRequest(BaseModel):
    transcript: str


class TwinVerifyRequest(BaseModel):
    confirm_failed: bool = False
    use_fresh_scan: bool = True


class LoadGameRequest(BaseModel):
    game_id: str


class TwinConfigRequest(BaseModel):
    enabled: bool


class TwinCalibrationRequest(BaseModel):
    board_corners: list[float]
    flip_files: bool = False
    board_flipped: bool = False


def parse_auto_move_game_id(game_id: str) -> tuple[str, str]:
    """Parse auto_move:uci or auto_move:uci##fen_before from GameSnapshot.game_id."""
    raw = (game_id or '').strip()
    if not raw.startswith('auto_move:'):
        return '', ''
    payload = raw[len('auto_move:'):].strip()
    if '##' in payload:
        uci, fen_before = payload.split('##', 1)
        return uci.strip(), fen_before.strip()
    return payload, ''


class WebBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__('chess_web_bridge')
        self.declare_parameter('http_host', '0.0.0.0')
        self.declare_parameter('http_port', 8080)
        self.declare_parameter('vision_mode', True)
        self.declare_parameter('enable_camera_preview', True)
        self.declare_parameter('camera_preview_topic', 'vision/debug/top_view')
        self.declare_parameter('camera_fallback_topic', '/camera/camera/color/image_raw')
        self.declare_parameter('auto_bot_move', True)
        self.declare_parameter('human_color', 'white')
        self.declare_parameter('board_orientation', 'standard')
        self.declare_parameter('engine_depth', 8)
        self.declare_parameter('difficulty', 'medium')
        self.declare_parameter('game_db_path', '~/.chess/games.db')
        self.declare_parameter('restore_saved_game', True)
        self.declare_parameter('voice_llm_enabled', False)
        self.declare_parameter('voice_llm_auto', True)
        self.declare_parameter('voice_llm_model', 'llama3.2:3b')
        self.declare_parameter('voice_llm_base_url', 'http://127.0.0.1:11434')
        self.declare_parameter('twin_enabled', True)
        self.declare_parameter('twin_auto_on_confirm_fail', True)
        self.declare_parameter('twin_webcam_device', 10)
        self.declare_parameter('twin_model_path', default_side_model_path())
        self.declare_parameter('twin_calibration_path', '')
        self.declare_parameter('twin_conf_threshold', 0.15)
        self.declare_parameter('twin_iou_threshold', 0.5)
        self.declare_parameter('twin_imgsz', 640)
        self.declare_parameter('twin_device', '')
        self.declare_parameter('twin_webcam_fps', 30)
        self.declare_parameter('twin_preview_interval_sec', 0.1)
        self.declare_parameter('twin_inference_interval_sec', 0.5)
        self.declare_parameter('twin_sideview_topic', '')
        self.declare_parameter('hand_enabled', True)
        try:
            _default_hand_model = default_hand_model_path()
        except FileNotFoundError:
            _default_hand_model = ''
        self.declare_parameter('hand_model_path', _default_hand_model)
        self.declare_parameter('hand_conf_threshold', 0.35)
        self.declare_parameter('hand_inference_interval_sec', 0.1)
        self.declare_parameter('hand_auto_confirm_enabled', False)
        self.declare_parameter('hand_safety_enabled', True)
        self.declare_parameter('hand_gone_confirm_delay_sec', 0.35)
        self.declare_parameter('hand_absent_frames', 4)
        self.declare_parameter('hand_confirm_cooldown_sec', 1.0)
        self.declare_parameter('hand_board_margin_px', 20.0)

        self.latest_fen = START_FEN
        self.latest_occupancy = [False] * 64
        self.latest_message = 'Reset을 눌러 초기 스캔을 실행하세요'
        self.latest_from = ''
        self.latest_to = ''
        self.latest_white_to_move = True
        self.latest_move_number = 1
        self.bot_status: BotStatus = 'idle'
        self.last_bot_move = ''
        self.human_captures: list[str] = []
        self.robot_captures: list[str] = []
        self.move_history: list[dict[str, Any]] = []
        self.eval_cp = 0
        self.bot_message = ''
        self.bot_speech_kind = 'move'
        self.game_phase: Literal['lobby', 'playing', 'finished'] = 'lobby'
        self.game_result: str = ''
        self.winner: Literal['human', 'robot', 'draw', ''] = ''
        self.is_check: bool = False
        self.promotion_notice: str = ''
        self._ply_counter = 0
        self.graveyard_slots: list[str | None] = [None] * 16
        self.human_graveyard_slots: list[str | None] = [None] * 16
        self._undo_snapshots: list[dict[str, Any]] = []
        self._pending_promotion: dict[str, str] | None = None
        self._pending_illegal_move: dict[str, str] | None = None
        self._latest_twin_report: dict[str, Any] | None = None
        self._twin_side_service = None
        self._sideview_lock = threading.Lock()
        self._sideview_live_jpeg: bytes | None = None
        self._sideview_piece_map: dict[str, str] = {}
        self._sideview_occupancy: list[bool] = [False] * 64
        self._sideview_message = ''
        self._sideview_preview_error = ''
        self._sideview_detections: list[dict[str, Any]] = []
        self._sideview_latest_frame: np.ndarray | None = None
        self._sideview_latest_frame_at = 0.0
        self._sideview_inference_busy = False
        self._sideview_updated_at = 0.0
        self._preview_updated_at = 0.0
        self._side_webcam_open_logged = False
        self._twin_runtime_lock = threading.Lock()
        self._twin_runtime_enabled = False
        self._hand_service = None
        self._hand_lock = threading.Lock()
        self._hand_in_board = False
        self._hand_raw_in_board = False
        self._hand_seen = False
        self._hand_present = False
        self._hand_inference_busy = False
        self._hand_raw_in_board_prev = False
        # Single-frame hand detections are noisy (motion blur off the moving
        # gripper, glare, etc.) and used to feed the robot's SafetyGate on every
        # frame with zero smoothing — a single spurious frame was enough to pause
        # an in-flight move, then resume, over and over. Require 2 consecutive
        # raw detections before treating it as active for the robot; a real hand
        # clears instantly (streak resets to 0) so no safety latency is added on
        # the way out, only a ~1-frame delay confirming a hand actually arrived.
        self._hand_raw_streak = 0
        self._hand_raw_confirm_frames = 2
        self._hand_safety_paused = False
        self._bot_status_before_pause: BotStatus = 'idle'
        self._hand_left_at = 0.0
        self._hand_confirm_pending = False
        self._hand_confirm_in_progress = False
        self._hand_confirm_timer = None
        self._last_hand_confirm_at = 0.0
        self._last_auto_move_uci = ''
        self._last_auto_move_at = 0.0
        self._auto_move_lock = threading.Lock()
        self._pending_vision_auto_move: tuple[str, str, str] | None = None
        self._vision_auto_move_in_progress = False
        self._last_bot_resume_attempt_at = 0.0
        self._last_recovery_sync_at = 0.0
        self._hand_last_published_in_board: bool | None = None
        self._bot_activity_started_at = 0.0
        self._hand_jpeg: bytes | None = None
        self._hand_preview_error = ''
        self._hand_detection_count = 0
        self._hand_updated_at = 0.0
        self._hand_auto_confirm_runtime = bool(
            self.get_parameter('hand_auto_confirm_enabled').value
        )
        self._hand_safety_runtime = bool(self.get_parameter('hand_safety_enabled').value)
        self._restore_in_progress = False
        self._board_reset_in_progress = False
        self._active_move_goal_handle = None
        self._active_restore_goal_handle = None
        self._executor: MultiThreadedExecutor | None = None
        self._service_call_lock = threading.Lock()
        self._active_game_id = ''
        self._saved_game_restored = False
        db_path = str(self.get_parameter('game_db_path').value)
        self._game_store = GameStore(db_path)

        self._preview_lock = threading.Lock()
        self._preview_jpeg: bytes | None = None
        self._preview_annotated_at = 0.0
        self._preview_bridge = CvBridge()

        self._bot_lock = threading.Lock()
        self._bot_busy = False
        self._bot_pending_fen = ''
        self._bot_worker_thread: threading.Thread | None = None
        self._bot_cancel_requested = False
        self._bot_session_active = False
        self._user_stop_pending = False
        self._engine_lock = threading.Lock()
        engine_depth = int(self.get_parameter('engine_depth').value)
        self._engine = StockfishClient(depth=engine_depth)
        self._engine.configure_opponent(self._difficulty())

        self.create_subscription(GameSnapshot, 'chess/game_snapshot', self._on_snapshot, 10)
        self.create_subscription(BoardState, 'chess/board_state', self._on_board, 10)
        self.create_subscription(BoardState, 'vision/live_occupancy', self._on_live_occupancy, 10)
        self._hand_pub = self.create_publisher(Bool, 'chess/hand_in_board', 10)
        self._timer_cb_group = ReentrantCallbackGroup()
        self._inference_lock = threading.Lock()
        if bool(self.get_parameter('enable_camera_preview').value):
            topic = str(self.get_parameter('camera_preview_topic').value)
            self.create_subscription(Image, topic, self._on_preview_image, 10)
            self.get_logger().info(f'Camera preview: {topic}')
        preview_interval = float(self.get_parameter('twin_preview_interval_sec').value)
        if self._twin_enabled() or self._hand_enabled():
            self.create_timer(
                preview_interval,
                self._timer_sideview_preview,
                callback_group=self._timer_cb_group,
            )
            self.get_logger().info(f'Side webcam preview every {preview_interval}s')
        if self._twin_enabled():
            infer_interval = float(self.get_parameter('twin_inference_interval_sec').value)
            self.create_timer(
                infer_interval,
                self._timer_sideview_inference,
                callback_group=self._timer_cb_group,
            )
            side_topic = str(self.get_parameter('twin_sideview_topic').value).strip()
            if side_topic:
                self.create_subscription(Image, side_topic, self._on_sideview_topic, 10)
            self.get_logger().info(
                f'Side-view twin inference every {infer_interval}s, '
                f'topic fallback={side_topic or "none"}'
            )
        if self._hand_enabled():
            hand_interval = float(self.get_parameter('hand_inference_interval_sec').value)
            self.create_timer(
                hand_interval,
                self._timer_hand_inference,
                callback_group=self._timer_cb_group,
            )
            self.create_timer(
                0.2,
                self._timer_hand_auto_confirm_poll,
                callback_group=self._timer_cb_group,
            )
            self.get_logger().info(f'Hand detection every {hand_interval}s')
        if self._vision_mode():
            self.create_timer(
                0.2,
                self._timer_game_flow_poll,
                callback_group=self._timer_cb_group,
            )
        self.reset_client = self.create_client(ResetBoard, 'chess/reset_board')
        self.scan_initial_client = self.create_client(ScanInitial, 'chess/scan_initial')
        self.confirm_player_client = self.create_client(ConfirmPlayerMove, 'chess/confirm_player_move')
        self.apply_robot_client = self.create_client(ApplyRobotMove, 'chess/apply_robot_move')
        self.set_board_client = self.create_client(SetBoard, 'chess/set_board')
        self.action_client = ActionClient(self, ExecuteMove, 'robot/execute_move')
        self.restore_action_client = ActionClient(self, RestoreBoard, 'robot/restore_board')
        self.robot_set_board_client = self.create_client(SetBoard, 'robot/set_board')
        self.robot_undo_client = self.create_client(UndoMoves, 'robot/undo_moves')
        self.robot_user_stop_client = self.create_client(Trigger, 'robot/user_stop')
        self.robot_user_stop_resume_client = self.create_client(Trigger, 'robot/user_stop_resume')
        self.robot_user_stop_abort_client = self.create_client(Trigger, 'robot/user_stop_abort')
        self.get_logger().info(
            f'Web bridge ready (human={self._human_color()}, auto_bot={self._auto_bot_move()}, '
            f'db={self._game_store.db_path})'
        )
        if bool(self.get_parameter('restore_saved_game').value):
            self._restore_timer = self.create_timer(2.0, self._try_restore_saved_game)

    def _game_record_summary(self, record: GameRecord) -> dict[str, Any]:
        return {
            'id': record.id,
            'updated_at': record.updated_at,
            'created_at': record.created_at,
            'is_active': record.is_active,
            'fen': record.fen,
            'human_color': record.human_color,
            'difficulty': record.difficulty,
            'board_orientation': record.board_orientation,
            'game_phase': record.game_phase,
            'game_result': record.game_result,
            'winner': record.winner,
            'move_count': len(record.move_history),
            'ply_counter': record.ply_counter,
            'bot_message': record.bot_message,
        }

    def list_saved_games(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [self._game_record_summary(r) for r in self._game_store.list_games(limit=limit)]

    def save_current_game(self) -> tuple[bool, str]:
        if self.game_phase == 'lobby' and not self._active_game_id:
            return False, '저장할 진행 중인 게임이 없습니다'
        self._ensure_active_game()
        try:
            record = self._game_record()
            self._game_store.mark_active(record.id)
            record.is_active = True
            self._game_store.save_game(record)
        except Exception as exc:  # noqa: BLE001
            return False, f'저장 실패: {exc}'
        self.latest_message = '게임을 저장했습니다'
        return True, 'saved'

    def _apply_loaded_game(self, record: GameRecord, *, message: str) -> tuple[bool, str]:
        self._game_store.mark_active(record.id)
        record.is_active = True
        self._prepare_robot_for_reset()
        self._apply_game_record(record)
        with self._bot_lock:
            self._bot_busy = False
            self._bot_pending_fen = ''
        self.bot_status = 'idle'
        self._hand_safety_paused = False
        self._reset_hand_tracking()

        logical_ok, logical_msg = self._sync_logical_board(record.fen)
        if not logical_ok:
            self.get_logger().warn(f'vision sync on load failed: {logical_msg}')
        sync_ok, sync_msg = self._sync_robot_board(record.fen)
        if not sync_ok:
            self.get_logger().warn(f'robot sync on load failed: {sync_msg}')
        self._refresh_game_phase(record.fen)
        self.eval_cp = self._eval_from_human_perspective_safe()
        self._bot_session_active = record.game_phase == 'playing'
        self.latest_message = message
        self._spin_for_updates()
        self._persist_game_state()
        if (
            self._bot_session_active
            and self.game_phase == 'playing'
            and self._auto_bot_move()
            and self._is_robot_turn(self.latest_white_to_move)
        ):
            self._maybe_play_bot_move(self.latest_fen)
        return True, message

    def load_saved_game(self, game_id: str) -> tuple[bool, str]:
        record = self._game_store.load_game(game_id)
        if record is None:
            return False, '저장된 게임을 찾을 수 없습니다'
        return self._apply_loaded_game(
            record,
            message='게임을 불러왔습니다. 실제 보드와 다르면 「보드 정리」를 사용하세요.',
        )

    def resume_active_saved_game(self) -> tuple[bool, str]:
        record = self._game_store.load_active_game()
        if record is None or record.game_phase == 'lobby':
            return False, '이어할 저장 게임이 없습니다'
        return self._apply_loaded_game(record, message='저장된 게임을 이어갑니다')

    def _maybe_restore_saved_game_once(self) -> None:
        if self._saved_game_restored:
            return
        if not bool(self.get_parameter('restore_saved_game').value):
            self._saved_game_restored = True
            return
        self._saved_game_restored = True
        if hasattr(self, '_restore_timer'):
            try:
                self._restore_timer.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._try_restore_saved_game()

    def shutdown(self) -> None:
        if self._twin_side_service is not None:
            self._twin_side_service.release()
        self._engine.stop()

    def _resolve_twin_calibration_path(self) -> str:
        configured = str(self.get_parameter('twin_calibration_path').value).strip()
        if configured:
            return configured
        candidates: list[Path] = []
        try:
            from ament_index_python.packages import get_package_share_directory

            share = Path(get_package_share_directory('chess_web_ui'))
            candidates.append(share / 'config' / 'board_twin_side_calibration.json')
        except Exception:  # noqa: BLE001
            pass
        module_dir = Path(__file__).resolve().parent
        candidates.append(module_dir.parent / 'config' / 'board_twin_side_calibration.json')
        for path in candidates:
            if path.is_file():
                return str(path)
        searched = ', '.join(str(path) for path in candidates)
        raise FileNotFoundError(
            f'board twin calibration not found (searched: {searched}). '
            'Run: colcon build --packages-select chess_web_ui'
        )

    def _default_twin_calibration_path(self) -> str:
        return self._resolve_twin_calibration_path()

    def _twin_enabled(self) -> bool:
        return bool(self.get_parameter('twin_enabled').value)

    def _hand_enabled(self) -> bool:
        return bool(self.get_parameter('hand_enabled').value)

    def _hand_active(self) -> bool:
        return self._hand_enabled()

    def _side_webcam_preview_active(self) -> bool:
        return self._hand_active() or self._twin_active()

    def _side_webcam_available(self) -> bool:
        return self._twin_enabled() or self._hand_enabled()

    def is_hand_auto_confirm_enabled(self) -> bool:
        return self._hand_auto_confirm_runtime

    def set_hand_auto_confirm_enabled(self, enabled: bool) -> None:
        self._hand_auto_confirm_runtime = bool(enabled)

    def is_hand_safety_enabled(self) -> bool:
        return self._hand_safety_runtime

    def set_hand_safety_enabled(self, enabled: bool) -> None:
        self._hand_safety_runtime = bool(enabled)
        if not self._hand_safety_runtime:
            # Immediately let the arm node know hand is clear so a pause already
            # latched from before disabling doesn't stick around, and so it stops
            # reacting to the hand topic going forward (_apply_hand_update also
            # stops publishing True while this is off).
            self._publish_hand_in_board(False, force=True)
            if self._hand_safety_paused:
                self._release_hand_safety_pause()

    def _get_hand_service(self) -> HandDetectorService:
        if self._hand_service is not None:
            return self._hand_service
        calibration_path = self._default_twin_calibration_path()
        configured_model = str(self.get_parameter('hand_model_path').value)
        self._hand_service = HandDetectorService(
            HandServiceConfig(
                model_path=configured_model,
                calibration_path=calibration_path,
                conf_threshold=float(self.get_parameter('hand_conf_threshold').value),
                board_margin_px=float(self.get_parameter('hand_board_margin_px').value),
                absent_frames=int(self.get_parameter('hand_absent_frames').value),
            )
        )
        return self._hand_service

    def _hand_blocks_robot(self) -> bool:
        """True when side-view hand is in the board ROI (raw or debounced)."""
        if not self._hand_safety_runtime:
            return False
        with self._hand_lock:
            return self._hand_in_board or self._hand_raw_in_board

    def _robot_hand_active(self, raw_in_board: bool, debounced_in_board: bool) -> bool:
        """Arm must stay paused while either raw or debounced hand is in ROI."""
        return raw_in_board or debounced_in_board

    def _publish_robot_hand_state(self, raw_in_board: bool, debounced_in_board: bool) -> None:
        self._publish_hand_in_board(self._robot_hand_active(raw_in_board, debounced_in_board))

    def _publish_hand_in_board(self, in_board: bool, *, force: bool = False) -> None:
        if not force and self._hand_last_published_in_board is in_board:
            return
        msg = Bool()
        msg.data = bool(in_board)
        self._hand_pub.publish(msg)
        self._hand_last_published_in_board = bool(in_board)

    def _republish_hand_clear_if_robot_active(
        self,
        *,
        in_board: bool,
        raw_in_board: bool,
    ) -> None:
        """Caller must not hold _hand_lock (or must pass state read under the lock)."""
        if not self._hand_enabled():
            return
        if in_board or raw_in_board:
            return
        if self.bot_status in ('moving', 'paused') or self._hand_safety_paused:
            self._publish_hand_in_board(False, force=True)

    def _ensure_hand_clear_for_robot(self) -> None:
        """Re-send hand-cleared while the arm may be blocked on SafetyGate."""
        with self._hand_lock:
            in_board = self._hand_in_board
            raw_in_board = self._hand_raw_in_board
        self._republish_hand_clear_if_robot_active(
            in_board=in_board,
            raw_in_board=raw_in_board,
        )

    def _recover_stale_bot_activity(self) -> bool:
        """Reset stuck bot UI/worker flags when the worker is gone — never abort in-flight motion."""
        if self._active_move_goal_handle is not None:
            return False
        with self._bot_lock:
            busy = self._bot_busy
            worker = self._bot_worker_thread
        worker_alive = worker is not None and worker.is_alive()
        if busy and worker_alive:
            return False
        stale_status = self.bot_status in ('thinking', 'moving', 'paused')
        orphan_busy = busy and not worker_alive
        stale_no_worker = stale_status and not worker_alive
        ghost_paused = (
            self.bot_status == 'paused'
            and not self._hand_safety_paused
            and not self._hand_blocks_robot()
            and not worker_alive
        )
        if not orphan_busy and not stale_no_worker and not ghost_paused:
            return False
        self.get_logger().warn(
            f'recovering stale bot activity status={self.bot_status} busy={busy}'
        )
        self._cancel_active_robot_goals()
        with self._bot_lock:
            self._bot_busy = False
            self._bot_pending_fen = ''
        self._hand_safety_paused = False
        self._bot_activity_started_at = 0.0
        self.bot_status = 'idle'
        self._ensure_hand_clear_for_robot()
        return True

    def _fen_fullmove_number(self, fen: str) -> int:
        try:
            return chess.Board((fen or '').strip()).fullmove_number
        except ValueError:
            return 0

    def _fen_looks_regressed(self, new_fen: str) -> bool:
        new_fen = (new_fen or '').strip()
        if not new_fen or not self.latest_fen:
            return False
        if len(self.move_history) == 0 and self._ply_counter == 0:
            return False
        try:
            cur = chess.Board(self.latest_fen)
            new = chess.Board(new_fen)
        except ValueError:
            return False
        if new.fullmove_number < cur.fullmove_number:
            return True
        if new_fen.split()[0] == START_FEN.split()[0] and cur.fullmove_number > 1:
            return True
        return False

    def _bot_fen_trustworthy(self, fen: str) -> bool:
        fen = (fen or '').strip()
        if not fen:
            return False
        hist_len = len(self.move_history)
        if hist_len == 0 and self._ply_counter == 0:
            return True
        try:
            board = chess.Board(fen)
        except ValueError:
            return False
        if fen.split()[0] == START_FEN.split()[0] and hist_len >= 2:
            # #region agent log
            agent_log(
                'web_bridge.py:_bot_fen_trustworthy',
                'REJECT start FEN with move history',
                {'fen': fen, 'move_history_len': hist_len, 'ply': self._ply_counter},
                hypothesis_id='A',
            )
            # #endregion
            return False
        expected_min_fullmove = max(1, (hist_len + 1) // 2)
        if board.fullmove_number < expected_min_fullmove and hist_len >= 2:
            # #region agent log
            agent_log(
                'web_bridge.py:_bot_fen_trustworthy',
                'REJECT fen behind move history',
                {
                    'fen': fen,
                    'fullmove': board.fullmove_number,
                    'expected_min': expected_min_fullmove,
                    'move_history_len': hist_len,
                },
                hypothesis_id='A',
            )
            # #endregion
            return False
        return True

    def _bot_motion_active(self) -> bool:
        with self._bot_lock:
            busy = self._bot_busy
            worker = self._bot_worker_thread
        return busy and worker is not None and worker.is_alive()

    def _enforce_human_turn_arm_safety(self) -> bool:
        """Stop/cancel any in-flight arm motion during the human turn."""
        if not self._bot_session_active or self.game_phase != 'playing':
            return False
        if not self._is_human_turn(self.latest_white_to_move):
            return False
        with self._bot_lock:
            worker = self._bot_worker_thread
        worker_alive = worker is not None and worker.is_alive()
        arm_busy = (
            worker_alive
            or self.bot_status in ('thinking', 'moving', 'paused')
            or self._active_move_goal_handle is not None
        )
        if not arm_busy:
            return False
        if self._active_move_goal_handle is not None:
            # #region agent log
            agent_log(
                'web_bridge.py:_enforce_human_turn_arm_safety',
                'SKIP enforce — execute_move goal in flight',
                {
                    'fen': self.latest_fen,
                    'bot_status': self.bot_status,
                    'white_to_move': self.latest_white_to_move,
                },
                hypothesis_id='E',
            )
            # #endregion
            return False
        if worker_alive:
            # Physical goal finished; worker is syncing FEN/history — do not user_stop.
            if self.bot_status in ('thinking', 'moving', 'paused'):
                self.bot_status = 'idle'
            self._hand_safety_paused = False
            # #region agent log
            agent_log(
                'web_bridge.py:_enforce_human_turn_arm_safety',
                'SKIP enforce — worker post-move sync',
                {
                    'fen': self.latest_fen,
                    'bot_status': self.bot_status,
                    'white_to_move': self.latest_white_to_move,
                },
                hypothesis_id='E',
            )
            # #endregion
            return False
        # #region agent log
        agent_log(
            'web_bridge.py:_enforce_human_turn_arm_safety',
            'STOP human turn arm',
            {
                'fen': self.latest_fen,
                'human_color': self._human_color(),
                'white_to_move': self.latest_white_to_move,
                'bot_status': self.bot_status,
                'worker_alive': worker_alive,
                'active_goal': self._active_move_goal_handle is not None,
            },
            hypothesis_id='E',
        )
        # #endregion
        self.get_logger().warn(
            'human turn — stopping robot arm (motion blocked during player turn)'
        )
        self._bot_cancel_requested = True
        self._cancel_active_robot_goals()
        self._call_trigger_service(self.robot_user_stop_client, timeout_sec=3.0)
        with self._bot_lock:
            self._bot_busy = False
            self._bot_pending_fen = ''
        self._bot_cancel_requested = False
        self.bot_status = 'idle'
        self._hand_safety_paused = False
        self._publish_hand_in_board(False, force=True)
        return True

    def _resolve_bot_status_after_hand_release(self) -> None:
        """Restore bot UI state after hand safety pause — never block human on stale 'moving'."""
        if self._active_move_goal_handle is not None:
            self.bot_status = 'moving'
            return
        if not self._bot_motion_active():
            self.bot_status = 'idle'
            return
        if self._is_human_turn(self.latest_white_to_move):
            self.bot_status = 'idle'
            return
        restore = self._bot_status_before_pause
        self.bot_status = restore if restore in ('thinking', 'moving') else 'idle'

    def _release_hand_safety_pause(self) -> None:
        if self._hand_blocks_robot():
            return
        was_paused = self._hand_safety_paused
        self._hand_safety_paused = False
        if was_paused or self.bot_status == 'paused':
            self._resolve_bot_status_after_hand_release()
        self._publish_hand_in_board(False, force=True)
        self._ensure_hand_clear_for_robot()
        if was_paused:
            self.get_logger().info('hand cleared — robot safety pause released')
        # #region agent log
        agent_log(
            'web_bridge.py:_release_hand_safety_pause',
            'hand pause released',
            {
                'was_paused': was_paused,
                'bot_status': self.bot_status,
                'bot_motion_active': self._bot_motion_active(),
                'hand_raw': self._hand_raw_in_board,
                'hand_debounced': self._hand_in_board,
                'white_to_move': self.latest_white_to_move,
                'human_color': self._human_color(),
            },
            hypothesis_id='C',
        )
        # #endregion
        self._try_process_pending_vision_auto_move()
        self._maybe_resume_bot_after_player_move()

    def _update_hand_safety(self, raw_in_board: bool, debounced_in_board: bool) -> None:
        if not self._hand_safety_runtime:
            return
        if self._is_human_turn(self.latest_white_to_move):
            self._enforce_human_turn_arm_safety()
            return
        hand_blocks = self._robot_hand_active(raw_in_board, debounced_in_board)
        robot_active = (
            self.bot_status in ('thinking', 'moving', 'paused')
            or self._restore_in_progress
            or self._bot_busy
        )
        if hand_blocks and robot_active and not self._hand_safety_paused:
            self._hand_safety_paused = True
            if self.bot_status != 'paused':
                self._bot_status_before_pause = self.bot_status
            self.bot_status = 'paused'
            self.get_logger().info('hand on board — robot paused for safety')
        elif not hand_blocks and self._hand_safety_paused:
            self._release_hand_safety_pause()

    def _schedule_hand_auto_confirm(self) -> None:
        if not self._hand_auto_confirm_runtime:
            return
        if self.game_phase != 'playing':
            return
        if not self._is_human_turn(self.latest_white_to_move):
            return
        if self._bot_busy or self._hand_confirm_in_progress:
            self._recover_stale_bot_activity()
            if self._bot_busy or self._hand_confirm_in_progress:
                return
        cooldown = float(self.get_parameter('hand_confirm_cooldown_sec').value)
        if time.time() - self._last_hand_confirm_at < cooldown:
            return
        self._hand_confirm_pending = True

    def _maybe_run_hand_auto_confirm(self) -> None:
        if not self._hand_confirm_pending:
            return
        delay = float(self.get_parameter('hand_gone_confirm_delay_sec').value)
        if self._hand_left_at <= 0.0:
            return
        if time.time() - self._hand_left_at < delay:
            return
        if self._hand_in_board or self._hand_raw_in_board:
            self._hand_confirm_pending = False
            return
        self._hand_confirm_pending = False
        self._hand_confirm_in_progress = True
        self._last_hand_confirm_at = time.time()
        self.get_logger().info('hand left board — auto confirm_player_move')
        if self._hand_confirm_timer is not None:
            try:
                self._hand_confirm_timer.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._hand_confirm_timer = self.create_timer(0.05, self._execute_hand_auto_confirm)

    def _execute_hand_auto_confirm(self) -> None:
        if self._hand_confirm_timer is not None:
            try:
                self._hand_confirm_timer.cancel()
            except Exception:  # noqa: BLE001
                pass
            self._hand_confirm_timer = None

        def _run() -> None:
            try:
                if not self._is_human_turn(self.latest_white_to_move):
                    agent_log(
                        'web_bridge.py:_execute_hand_auto_confirm',
                        'skipped robot turn',
                        {'fen': self.latest_fen},
                        hypothesis_id='C',
                    )
                    return
                if self._recent_player_move_applied():
                    agent_log(
                        'web_bridge.py:_execute_hand_auto_confirm',
                        'skipped duplicate confirm after auto move',
                        {'uci': self._last_auto_move_uci},
                        hypothesis_id='C',
                    )
                    self._maybe_resume_bot_after_player_move()
                    return
                success, message, from_sq, to_sq = self.confirm_player_move()
                self.get_logger().info(
                    f'hand auto confirm: success={success} {from_sq}->{to_sq} msg={message}'
                )
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'hand auto confirm failed: {exc}')
            finally:
                self._hand_confirm_in_progress = False

        threading.Thread(target=_run, daemon=True).start()

    def _store_hand_preview(self, service: HandDetectorService, frame, update) -> None:
        try:
            annotated = service.annotate_frame(frame, update.detections)
            preview = draw_calibration_overlay(annotated, service.calibration.board_corners)
            state = 'IN BOARD' if update.hand_in_board else (
                'ENTERING' if any(det.in_board_roi for det in update.detections) else (
                    'NEAR' if update.hand_present else ('SEEN' if update.hand_seen else 'CLEAR')
                )
            )
            cv2.putText(
                preview,
                f'hand: {state}  auto={self._hand_auto_confirm_runtime}',
                (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0) if update.hand_in_board else (200, 200, 200),
                2,
                cv2.LINE_AA,
            )
            ok, encoded = cv2.imencode('.jpg', preview, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                with self._hand_lock:
                    self._hand_preview_error = 'hand jpeg encode failed'
                return
            with self._hand_lock:
                self._hand_jpeg = encoded.tobytes()
                self._hand_detection_count = len(update.detections)
                self._hand_preview_error = ''
        except Exception as exc:  # noqa: BLE001
            with self._hand_lock:
                self._hand_preview_error = str(exc)

    def _capture_fresh_side_frame(self) -> np.ndarray | None:
        """Always read the side webcam directly — never reuse a stale cached frame."""
        if not self._side_webcam_available():
            return None
        service = self._get_twin_side_service()
        if service is None:
            return None
        frame = service.capture_webcam_frame()
        if frame is None or frame.size == 0:
            return None
        now = time.time()
        with self._sideview_lock:
            self._sideview_latest_frame = frame.copy()
            self._sideview_latest_frame_at = now
        if not self._side_webcam_open_logged and self._twin_side_service is not None:
            webcam = getattr(self._twin_side_service, '_webcam', None)
            if webcam is not None and webcam.active_device is not None:
                self._side_webcam_open_logged = True
                self.get_logger().info(
                    f'side webcam active: /dev/video{webcam.active_device} '
                    f'{webcam.actual_width}x{webcam.actual_height}@{webcam.actual_fps:.0f}fps'
                )
        return frame

    def _capture_hand_frame(self) -> np.ndarray | None:
        return self._get_side_frame_for_inference()

    def _get_side_frame_for_inference(self, *, max_age_sec: float = 0.5) -> np.ndarray | None:
        """Reuse the latest preview frame when fresh to avoid triple webcam reads."""
        with self._sideview_lock:
            frame = self._sideview_latest_frame
            captured_at = self._sideview_latest_frame_at
        if frame is not None and frame.size > 0 and time.time() - captured_at <= max_age_sec:
            return frame.copy()
        return self._capture_fresh_side_frame()

    def _hand_leave_event(self, *, raw_in_board: bool) -> None:
        if self._hand_raw_in_board_prev and not raw_in_board:
            self._hand_left_at = time.time()
            self._schedule_hand_auto_confirm()
        self._hand_raw_in_board_prev = raw_in_board

    def _apply_hand_update(self, service: HandDetectorService, frame, update) -> None:
        raw_in_board = any(det.in_board_roi for det in update.detections)
        self._store_hand_preview(service, frame, update)
        with self._hand_lock:
            self._hand_in_board = update.hand_in_board
            self._hand_raw_in_board = raw_in_board
            self._hand_seen = update.hand_seen
            self._hand_present = update.hand_present
            self._hand_updated_at = time.time()
            if raw_in_board or update.hand_in_board:
                self._hand_confirm_pending = False
            if update.entered_board:
                self._hand_confirm_pending = False
            if update.left_board:
                self._hand_left_at = time.time()
                self._schedule_hand_auto_confirm()
            self._hand_leave_event(raw_in_board=raw_in_board)
            if raw_in_board:
                self._hand_raw_streak += 1
            else:
                self._hand_raw_streak = 0
            raw_confirmed = self._hand_raw_streak >= self._hand_raw_confirm_frames
            robot_hand = (
                self._robot_hand_active(raw_confirmed, update.hand_in_board)
                if self._hand_safety_runtime
                else False
            )
            self._publish_hand_in_board(robot_hand)
        self._update_hand_safety(raw_in_board, update.hand_in_board)
        self._maybe_run_hand_auto_confirm()

    def _refresh_hand_preview_from_frame(self, frame: np.ndarray) -> None:
        """Update hand annotated JPEG from the latest side frame + cached detections."""
        if not self._hand_active():
            return
        try:
            service = self._get_hand_service()
            tracker = service.tracker
            dets = list(tracker._last_detections)
            raw_in_board = any(det.in_board_roi for det in dets)
            preview_update = HandPresenceUpdate(
                state=tracker.state,
                hand_in_board=tracker.hand_in_board,
                hand_seen=bool(dets),
                hand_present=bool(dets) and not raw_in_board,
                detections=dets,
            )
            self._store_hand_preview(service, frame, preview_update)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(
                f'hand preview refresh failed: {exc}',
                throttle_duration_sec=10.0,
            )

    def _hand_inference_capture_failed(self, err: str) -> None:
        with self._hand_lock:
            self._hand_updated_at = time.time()
        self.get_logger().warn(f'hand capture failed: {err}', throttle_duration_sec=5.0)

    def _timer_game_flow_poll(self) -> None:
        self._enforce_human_turn_arm_safety()
        self._try_process_pending_vision_auto_move()
        self._maybe_resume_bot_after_player_move()

    def _timer_hand_auto_confirm_poll(self) -> None:
        self._ensure_hand_clear_for_robot()
        self._try_process_pending_vision_auto_move()
        self._maybe_resume_bot_after_player_move()
        if self._hand_auto_confirm_runtime:
            self._maybe_run_hand_auto_confirm()
        if not self._hand_active():
            return
        with self._hand_lock:
            last = self._hand_updated_at
        now = time.time()
        with self._sideview_lock:
            preview_at = self._preview_updated_at
        preview_stale = preview_at <= 0.0 or now - preview_at > 5.0
        hand_stale = last > 0.0 and now - last > 5.0
        if (
            hand_stale
            and preview_stale
            and not self._hand_inference_busy
        ):
            self.get_logger().warn(
                'hand pipeline stale >5s — reopening side webcam',
                throttle_duration_sec=15.0,
            )
            if self._twin_side_service is not None:
                self._twin_side_service.release()
                self._twin_side_service = None

    def _timer_hand_inference(self) -> None:
        if not self._hand_active() or self._hand_inference_busy:
            return
        self._hand_inference_busy = True

        def _run() -> None:
            try:
                service = self._get_hand_service()
                frame = self._capture_hand_frame()
                if frame is None or frame.size == 0:
                    err = ''
                    if self._twin_side_service is not None:
                        err = self._twin_side_service.webcam_last_error()
                    self._hand_inference_capture_failed(err or 'side webcam capture failed')
                    return
                with self._inference_lock:
                    update = service.update_from_frame(frame)
                self._apply_hand_update(service, frame, update)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'hand inference error: {exc}')
            finally:
                self._hand_inference_busy = False

        threading.Thread(target=_run, daemon=True).start()

    def _twin_active(self) -> bool:
        with self._twin_runtime_lock:
            return self._twin_enabled() and self._twin_runtime_enabled

    def is_twin_runtime_enabled(self) -> bool:
        with self._twin_runtime_lock:
            return self._twin_runtime_enabled

    def set_twin_runtime_enabled(self, enabled: bool) -> None:
        with self._twin_runtime_lock:
            self._twin_runtime_enabled = bool(enabled)
        if not enabled:
            self._release_twin_resources()
        else:
            self._warm_sideview()
        self.get_logger().info(f'sideview twin runtime enabled={enabled}')

    def save_side_calibration(
        self,
        board_corners: list[float],
        *,
        flip_files: bool = False,
        board_flipped: bool = False,
    ) -> tuple[bool, str]:
        if len(board_corners) != 8:
            return False, 'board_corners must have 8 numbers (a1,h1,h8,a8)'
        path = self._default_twin_calibration_path()
        payload = {
            'board_corners': [float(v) for v in board_corners],
            'flip_files': bool(flip_files),
            'board_flipped': bool(board_flipped),
            'webcam_device': int(self.get_parameter('twin_webcam_device').value),
            'camera_width': 1280,
            'camera_height': 720,
            '_comment': 'Order: a1, h1, h8, a8 image coordinates.',
        }
        Path(path).write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
        if self._twin_side_service is not None:
            self._twin_side_service.calibration = SideViewCalibration.from_json_file(path)
        if self._hand_service is not None:
            self._hand_service.reload_calibration()
        self._warm_sideview()
        return True, f'saved side calibration to {path}'

    def _warm_sideview(self) -> None:
        if not self._twin_active():
            return
        self._timer_sideview_preview()
        if not self._sideview_inference_busy:
            self._timer_sideview_inference()

    def get_side_calibration_payload(self) -> dict[str, Any]:
        path = self._default_twin_calibration_path()
        cal = SideViewCalibration.from_json_file(path)
        return {
            'calibration_path': path,
            'board_corners': [coord for point in cal.board_corners for coord in point],
            'flip_files': cal.flip_files,
            'board_flipped': cal.board_flipped,
            'webcam_device': cal.webcam_device,
            'camera_width': cal.camera_width,
            'camera_height': cal.camera_height,
        }

    def _release_twin_resources(self) -> None:
        # Hand detection shares the side webcam — never release while hand is active.
        if not self._hand_active() and self._twin_side_service is not None:
            self._twin_side_service.release()
            self._twin_side_service = None
        with self._sideview_lock:
            self._sideview_live_jpeg = None
            self._sideview_piece_map = {}
            self._sideview_occupancy = [False] * 64
            self._sideview_message = ''
            self._sideview_preview_error = ''
            self._sideview_detections = []
            self._sideview_latest_frame = None
            self._sideview_latest_frame_at = 0.0
            self._sideview_updated_at = 0.0
            self._preview_updated_at = 0.0

    def _apply_sideview_estimate(
        self,
        estimate: Any,
        annotated: np.ndarray | None,
        msg: str,
    ) -> None:
        del annotated
        with self._sideview_lock:
            if estimate is not None:
                self._sideview_piece_map = dict(estimate.piece_map)
                self._sideview_occupancy = list(estimate.occupancy)
                self._sideview_detections = [
                    {
                        'class_name': det.class_name,
                        'symbol': det.symbol,
                        'square': det.square,
                        'confidence': det.confidence,
                        'center_x': det.center_x,
                        'center_y': det.center_y,
                        'bbox': list(det.bbox),
                    }
                    for det in estimate.detections
                ]
                self._sideview_message = msg or estimate.message
            else:
                self._sideview_message = msg or 'sideview inference failed'
            self._sideview_updated_at = time.time()

    def _get_twin_side_service(self):
        if self._twin_side_service is not None:
            return self._twin_side_service
        if not self._side_webcam_available():
            return None
        calibration_path = self._default_twin_calibration_path()
        configured_model = str(self.get_parameter('twin_model_path').value)
        model_path = resolve_side_model_path(configured_model)
        if model_path != configured_model:
            self.get_logger().info(f'sideview model: {model_path}')
        elif not Path(model_path).is_file() and '/' in model_path:
            self.get_logger().warn(
                f'sideview model {model_path} not found locally; using remote/HF resolve'
            )
        self._twin_side_service = build_side_service_from_paths(
            model_path=model_path,
            calibration_path=calibration_path,
            conf_threshold=float(self.get_parameter('twin_conf_threshold').value),
            iou_threshold=float(self.get_parameter('twin_iou_threshold').value),
            imgsz=int(self.get_parameter('twin_imgsz').value),
            device=str(self.get_parameter('twin_device').value),
            webcam_fps=int(self.get_parameter('twin_webcam_fps').value),
        )
        device = int(self.get_parameter('twin_webcam_device').value)
        self._twin_side_service.calibration.webcam_device = device
        self.get_logger().info(
            f'side webcam configured: /dev/video{device} (C270 side cam expected at 10; laptop cam is 8)'
        )
        return self._twin_side_service

    def _timer_sideview_preview(self) -> None:
        if not self._side_webcam_preview_active():
            return
        try:
            service = self._get_twin_side_service()
            if service is None:
                return
            frame = self._capture_fresh_side_frame()
            if frame is None:
                err = service.webcam_last_error() or 'side webcam capture failed'
                with self._sideview_lock:
                    self._sideview_preview_error = err
                return
            preview_frame = draw_calibration_overlay(frame, service.calibration.board_corners)
            stamp = time.strftime('%H:%M:%S') + f'.{int(time.time() * 10) % 10}'
            cv2.putText(
                preview_frame,
                f'live {stamp}',
                (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            ok, encoded = cv2.imencode('.jpg', preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                with self._sideview_lock:
                    self._sideview_preview_error = 'webcam jpeg encode failed'
                return
            with self._sideview_lock:
                self._sideview_live_jpeg = encoded.tobytes()
                self._sideview_preview_error = ''
                self._preview_updated_at = time.time()
            if self._hand_active():
                self._refresh_hand_preview_from_frame(frame)
        except Exception as exc:  # noqa: BLE001
            with self._sideview_lock:
                self._sideview_preview_error = str(exc)
            self.get_logger().warn(
                f'sideview preview failed: {exc}',
                throttle_duration_sec=10.0,
            )

    def _on_sideview_topic(self, msg: Image) -> None:
        if not self._twin_active():
            return
        try:
            frame = self._preview_bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return
            with self._sideview_lock:
                self._sideview_live_jpeg = encoded.tobytes()
                self._sideview_preview_error = ''
                self._preview_updated_at = time.time()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(
                f'sideview topic preview failed: {exc}',
                throttle_duration_sec=10.0,
            )

    def _timer_sideview_inference(self) -> None:
        if not self._twin_active() or self._sideview_inference_busy:
            return
        self._sideview_inference_busy = True

        def _run() -> None:
            started = time.monotonic()
            estimate = None
            try:
                service = self._get_twin_side_service()
                frame = self._get_side_frame_for_inference()
                if frame is None:
                    err = service.webcam_last_error() if service else 'no sideview frame for inference'
                    err = err or 'no sideview frame for inference'
                    self._apply_sideview_estimate(None, None, err)
                    return
                with self._inference_lock:
                    estimate, _raw, _annotated, msg = service.detect_and_annotate_from_frame(
                        frame,
                        recorded_fen=self.latest_fen,
                    )
                self._apply_sideview_estimate(estimate, None, msg)
                elapsed = time.monotonic() - started
                det_count = len(estimate.detections) if estimate is not None else 0
                raw_count = len(_raw) if _raw else 0
                self.get_logger().info(
                    f'sideview inference {elapsed:.2f}s, '
                    f'{raw_count} raw / {det_count} mapped detections'
                )
            except Exception as exc:  # noqa: BLE001
                self._apply_sideview_estimate(
                    estimate,
                    None,
                    f'sideview inference error: {exc}',
                )
                self.get_logger().error(f'sideview inference failed: {exc}')
            finally:
                self._sideview_inference_busy = False

        threading.Thread(target=_run, daemon=True).start()

    def get_sideview_jpeg(self) -> bytes | None:
        with self._sideview_lock:
            return self._sideview_live_jpeg

    def get_hand_preview_jpeg(self) -> bytes | None:
        with self._hand_lock:
            return self._hand_jpeg

    def get_twin_live_payload(self) -> dict[str, Any]:
        available = self._twin_enabled()
        runtime_enabled = self.is_twin_runtime_enabled()
        with self._hand_lock:
            hand_in_board = self._hand_in_board
            hand_seen = self._hand_seen
            hand_present = self._hand_present
            hand_safety_paused = self._hand_safety_paused
            hand_preview_available = self._hand_jpeg is not None
            hand_preview_error = self._hand_preview_error
            hand_detection_count = self._hand_detection_count
            hand_updated_at = self._hand_updated_at
        hand_available = self._hand_enabled()
        hand_fields = {
            'hand_available': hand_available,
            'hand_in_board': hand_in_board if hand_available else False,
            'hand_seen': hand_seen if hand_available else False,
            'hand_present': hand_present if hand_available else False,
            'hand_safety_paused': hand_safety_paused if hand_available else False,
            'hand_auto_confirm_enabled': self._hand_auto_confirm_runtime,
            'hand_safety_enabled': self._hand_safety_runtime,
            'hand_preview_available': hand_preview_available if hand_available else False,
            'hand_preview_error': hand_preview_error if hand_available else '',
            'hand_detection_count': hand_detection_count if hand_available else 0,
            'hand_updated_at': hand_updated_at if hand_available else 0.0,
        }
        if not available or not runtime_enabled:
            with self._sideview_lock:
                preview_updated_at = self._preview_updated_at
                preview_error = self._sideview_preview_error
                preview_available = self._sideview_live_jpeg is not None
            return {
                'enabled': False,
                'available': available,
                'runtime_enabled': runtime_enabled,
                'preview_available': preview_available if hand_available else False,
                'preview_error': preview_error if hand_available else '',
                'preview_updated_at': preview_updated_at if hand_available else 0.0,
                **hand_fields,
            }
        recorded_occ = list(self.latest_occupancy)
        with self._sideview_lock:
            sv_occ = list(self._sideview_occupancy)
            sv_map = dict(self._sideview_piece_map)
            sv_dets = list(self._sideview_detections)
            msg = self._sideview_message
            preview_error = self._sideview_preview_error
            preview_available = self._sideview_live_jpeg is not None
            updated_at = self._sideview_updated_at
            preview_updated_at = self._preview_updated_at
        return {
            'enabled': True,
            'available': True,
            'runtime_enabled': True,
            'recorded_occupancy': recorded_occ,
            'sideview_occupancy': sv_occ,
            'sideview_piece_map': sv_map,
            'sideview_detections': sv_dets,
            'diff_squares': occupancy_diff_squares(recorded_occ, sv_occ),
            'message': msg,
            'preview_available': preview_available,
            'preview_error': preview_error,
            'sideview_updated_at': updated_at,
            'preview_updated_at': preview_updated_at,
            **hand_fields,
        }

    def verify_board_twin(
        self,
        *,
        confirm_failed: bool = False,
        use_fresh_scan: bool = True,
    ) -> dict[str, Any]:
        del use_fresh_scan
        if not self._twin_enabled():
            payload = {
                'success': False,
                'aligned': False,
                'message': 'board twin verification is disabled',
                'recorded_fen': self.latest_fen,
            }
            self._latest_twin_report = payload
            return payload
        if not self._twin_active():
            payload = {
                'success': False,
                'aligned': True,
                'message': '사이드뷰 보드 검증이 꺼져 있습니다',
                'recorded_fen': self.latest_fen,
            }
            self._latest_twin_report = payload
            return payload

        result = run_board_twin_verify(
            recorded_fen=self.latest_fen,
            side_service=self._get_twin_side_service(),
            confirm_failed=confirm_failed,
        )
        payload = result.to_payload()
        self._latest_twin_report = payload
        self.get_logger().info(
            f'board twin verify aligned={result.aligned} mismatches={len(result.mismatches)}'
        )
        return payload

    def _vision_mode(self) -> bool:
        return bool(self.get_parameter('vision_mode').value)

    def _auto_bot_move(self) -> bool:
        return bool(self.get_parameter('auto_bot_move').value)

    def _human_color(self) -> str:
        color = str(self.get_parameter('human_color').value).strip().lower()
        return color if color in {'white', 'black'} else 'white'

    def _board_orientation(self) -> str:
        orientation = str(self.get_parameter('board_orientation').value).strip().lower()
        return orientation if orientation in {'standard', 'flipped'} else 'standard'

    def _robot_color(self) -> str:
        return 'black' if self._human_color() == 'white' else 'white'

    def _is_robot_turn(self, white_to_move: bool) -> bool:
        robot_is_white = self._human_color() == 'black'
        return white_to_move == robot_is_white

    def _is_human_turn(self, white_to_move: bool) -> bool:
        return not self._is_robot_turn(white_to_move)

    def _voice_llm_enabled(self) -> bool:
        return bool(self.get_parameter('voice_llm_enabled').value)

    def _voice_llm_auto(self) -> bool:
        return bool(self.get_parameter('voice_llm_auto').value)

    def _voice_llm_model(self) -> str:
        return str(self.get_parameter('voice_llm_model').value).strip() or 'llama3.2:3b'

    def _voice_llm_base_url(self) -> str:
        return str(self.get_parameter('voice_llm_base_url').value).strip() or 'http://127.0.0.1:11434'

    def _uci_is_human_move(self, fen: str, uci: str) -> bool:
        uci = (uci or '').strip().lower()
        if len(uci) < 4:
            return False
        from_sq = uci[:2]
        try:
            board = chess.Board(fen)
            square = chess.parse_square(from_sq)
        except ValueError:
            return False
        piece = board.piece_at(square)
        if piece is None:
            return False
        human_is_white = self._human_color() == 'white'
        return piece.color == chess.WHITE if human_is_white else piece.color == chess.BLACK

    def _uci_is_robot_move(self, fen: str, uci: str) -> bool:
        uci = (uci or '').strip().lower()
        if len(uci) < 4:
            return False
        legal = resolve_legal_uci_full(uci, fen)
        if legal is None:
            return False
        return not self._uci_is_human_move(fen, legal)

    @staticmethod
    def _is_illegal_move_result(result, *, legal: bool, uci: str) -> bool:
        msg = (getattr(result, 'message', '') or '').lower()
        if 'illegal move' in msg:
            return True
        return bool(getattr(result, 'success', False) and uci and not legal)

    def _difficulty(self) -> Difficulty:
        level = str(self.get_parameter('difficulty').value).strip().lower()
        if level in {'beginner', 'easy', 'medium', 'hard', 'master'}:
            return level  # type: ignore[return-value]
        return 'medium'

    def _bot_profile_payload(self) -> dict[str, str]:
        return get_bot_profile(self._difficulty())

    def _set_bot_banter(self, line) -> None:
        self.bot_message = line.text
        self.bot_speech_kind = line.kind

    def _eval_from_human_perspective(self, fen: str | None = None) -> int:
        target = fen or self.latest_fen
        white_cp = self._with_engine(lambda: self._engine.evaluate(target))
        if self._human_color() == 'white':
            return white_cp
        return -white_cp

    def _uci_to_san(self, fen_before: str, uci: str) -> str:
        try:
            board = chess.Board(fen_before)
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                return uci
            return board.san(move)
        except (ValueError, AssertionError):
            return uci

    def _is_legal_uci(self, fen: str, uci: str) -> bool:
        return resolve_legal_uci_full(uci, fen) is not None

    def _with_engine(self, fn, *, blocking: bool = True):
        if blocking:
            with self._engine_lock:
                return fn()
        if self._engine_lock.acquire(blocking=False):
            try:
                return fn()
            finally:
                self._engine_lock.release()
        return None

    def _eval_from_human_perspective_safe(self, fen: str | None = None, default: int = 0) -> int:
        target = fen or self.latest_fen
        white_cp = self._with_engine(lambda: self._engine.evaluate(target), blocking=False)
        if white_cp is None:
            return default
        if self._human_color() == 'white':
            return white_cp
        return -white_cp

    def _append_move_history(
        self,
        *,
        fen_before: str,
        uci: str,
        color: str,
        eval_cp: int,
        quality: str | None = None,
    ) -> None:
        self._ply_counter += 1
        entry: dict[str, Any] = {
            'ply': self._ply_counter,
            'san': self._uci_to_san(fen_before, uci),
            'uci': uci,
            'from': uci[:2],
            'to': uci[2:4],
            'color': color,
            'eval_cp': eval_cp,
        }
        if quality:
            entry['quality'] = quality
        self.move_history.append(entry)
        self._persist_game_state()

    def _game_record(self) -> GameRecord:
        return GameRecord(
            id=self._active_game_id or 'unsaved',
            created_at='',
            updated_at='',
            is_active=True,
            fen=self.latest_fen,
            human_color=self._human_color(),
            difficulty=self._difficulty(),
            board_orientation=self._board_orientation(),
            game_phase=self.game_phase,
            game_result=self.game_result,
            winner=self.winner,
            eval_cp=self.eval_cp,
            bot_status=self.bot_status,
            graveyard_slots=list(self.graveyard_slots),
            human_graveyard_slots=list(self.human_graveyard_slots),
            human_captures=list(self.human_captures),
            robot_captures=list(self.robot_captures),
            move_history=list(self.move_history),
            ply_counter=self._ply_counter,
            last_bot_move=self.last_bot_move,
            bot_message=self.bot_message,
        )

    def _ensure_active_game(self) -> None:
        if self._active_game_id:
            return
        record = self._game_store.create_new_game(
            fen=self.latest_fen,
            human_color=self._human_color(),
            difficulty=self._difficulty(),
            game_phase=self.game_phase if self.game_phase != 'lobby' else 'playing',
            bot_message=self.bot_message,
        )
        self._active_game_id = record.id
        self.graveyard_slots = list(record.graveyard_slots)
        self.human_graveyard_slots = list(record.human_graveyard_slots)

    def _persist_game_state(self) -> None:
        if not self._active_game_id:
            return
        try:
            self._game_store.save_game(self._game_record())
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'failed to persist game state: {exc}')

    def _apply_game_record(self, record: GameRecord) -> None:
        self._active_game_id = record.id
        self.latest_fen = record.fen
        self.latest_occupancy = occupancy_from_fen(record.fen)
        parts = record.fen.split()
        self.latest_white_to_move = len(parts) > 1 and parts[1] == 'w'
        self.human_captures = list(record.human_captures)
        self.robot_captures = list(record.robot_captures)
        self.move_history = list(record.move_history)
        self._ply_counter = record.ply_counter
        self.eval_cp = record.eval_cp
        self.bot_message = record.bot_message
        self.bot_speech_kind = 'move'
        self.game_phase = record.game_phase  # type: ignore[assignment]
        self.game_result = record.game_result
        self.winner = record.winner  # type: ignore[assignment]
        self.bot_status = record.bot_status  # type: ignore[assignment]
        self.last_bot_move = record.last_bot_move
        self.graveyard_slots = list(record.graveyard_slots)
        self.human_graveyard_slots = list(record.human_graveyard_slots)
        self.is_check = chess.Board(record.fen).is_check()
        self.promotion_notice = ''
        orientation = getattr(record, 'board_orientation', 'standard') or 'standard'
        if orientation in {'standard', 'flipped'}:
            self.set_parameters([
                Parameter('human_color', Parameter.Type.STRING, record.human_color),
                Parameter('difficulty', Parameter.Type.STRING, record.difficulty),
                Parameter('board_orientation', Parameter.Type.STRING, orientation),
            ])
            self._with_engine(lambda: self._engine.configure_opponent(record.difficulty))  # type: ignore[arg-type]

    def _refresh_game_phase(self, fen: str) -> None:
        outcome = game_outcome(chess.Board(fen))
        self.is_check = chess.Board(fen).is_check()
        if outcome.is_over:
            self._update_game_over_state(fen)
        else:
            self.game_phase = 'playing'
            self.game_result = ''
            self.winner = ''

    def _sync_logical_board(self, fen: str) -> tuple[bool, str]:
        if not self._vision_mode():
            self._sync_from_fen(fen)
            return True, 'local FEN synced'
        result, err = self._call_service(
            self.set_board_client,
            SetBoard.Request(fen=fen),
            timeout_sec=10.0,
        )
        if result is None:
            return False, err
        if not result.success:
            return False, result.message
        if result.board_state is not None:
            self._apply_board_state_msg(result.board_state)
        if getattr(result, 'fen', ''):
            self._sync_from_fen(result.fen)
        else:
            self._sync_from_fen(fen)
        return True, result.message

    def _try_restore_saved_game(self) -> None:
        if (
            self.game_phase == 'playing'
            and (self.move_history or self._ply_counter > 0)
        ):
            # #region agent log
            agent_log(
                'web_bridge.py:_try_restore_saved_game',
                'SKIP restore — game already in progress',
                {
                    'fen': self.latest_fen,
                    'move_history_len': len(self.move_history),
                    'ply': self._ply_counter,
                },
                hypothesis_id='A',
            )
            # #endregion
            self.get_logger().info('Skip saved-game restore: game already in progress')
            return
        record = self._game_store.load_active_game()
        if record is None:
            self.get_logger().info('No saved game to restore')
            return
        if record.game_phase == 'lobby':
            return
        if self.latest_fen and record.fen:
            try:
                if self._fen_fullmove_number(self.latest_fen) > self._fen_fullmove_number(
                    record.fen
                ):
                    # #region agent log
                    agent_log(
                        'web_bridge.py:_try_restore_saved_game',
                        'SKIP restore — current fen ahead of saved',
                        {'current_fen': self.latest_fen, 'saved_fen': record.fen},
                        hypothesis_id='A',
                    )
                    # #endregion
                    return
            except ValueError:
                pass

        self.get_logger().info(
            f'Restoring saved game {record.id[:8]}… fen={record.fen.split()[0]} '
            f'moves={len(record.move_history)}'
        )
        self._apply_loaded_game(record, message='저장된 게임을 복원했습니다')

    def set_game_config(
        self,
        human_color: str,
        difficulty: str | None = None,
        board_orientation: str | None = None,
        *,
        hand_auto_confirm_enabled: bool | None = None,
    ) -> None:
        color = human_color.strip().lower()
        if color not in {'white', 'black'}:
            raise ValueError('human_color must be white or black')
        # Lobby "게임 시작" always resets next — stop any in-flight bot/poll work first.
        self._bot_session_active = False
        self._prepare_robot_for_reset()
        self._active_game_id = ''
        with self._auto_move_lock:
            self._pending_vision_auto_move = None
            self._vision_auto_move_in_progress = False
            self._last_auto_move_uci = ''
            self._last_auto_move_at = 0.0
        params = [Parameter('human_color', Parameter.Type.STRING, color)]
        if difficulty is not None:
            level = difficulty.strip().lower()
            if level not in {'beginner', 'easy', 'medium', 'hard', 'master'}:
                raise ValueError(
                    'difficulty must be beginner, easy, medium, hard, or master'
                )
            params.append(Parameter('difficulty', Parameter.Type.STRING, level))
            self._with_engine(lambda: self._engine.configure_opponent(level))  # type: ignore[arg-type]
        if board_orientation is not None:
            orientation = board_orientation.strip().lower()
            if orientation not in {'standard', 'flipped'}:
                raise ValueError('board_orientation must be standard or flipped')
            params.append(Parameter('board_orientation', Parameter.Type.STRING, orientation))
        if hand_auto_confirm_enabled is not None:
            self.set_hand_auto_confirm_enabled(hand_auto_confirm_enabled)
        self.set_parameters(params)
        self.get_logger().info(
            f'Game config: human={color}, robot={self._robot_color()}, '
            f'difficulty={self._difficulty()}, orientation={self._board_orientation()}'
        )

    def _recent_player_move_applied(self) -> bool:
        cooldown = float(self.get_parameter('hand_confirm_cooldown_sec').value)
        with self._auto_move_lock:
            return (
                bool(self._last_auto_move_uci)
                and time.time() - self._last_auto_move_at < cooldown
            )

    def _on_snapshot(self, msg: GameSnapshot) -> None:
        game_id = (msg.game_id or '').strip()
        if game_id.startswith('auto_move:'):
            uci, fen_before_from_id = parse_auto_move_game_id(game_id)
            fen_before_hint = fen_before_from_id
            if not fen_before_hint and msg.fen:
                if self._is_human_turn(self.latest_white_to_move):
                    fen_before_hint = (self.latest_fen or '').strip()
            if uci and msg.fen:
                if fen_before_hint:
                    try:
                        human_turn = self._is_human_turn(
                            chess.Board(fen_before_hint).turn == chess.WHITE
                        )
                    except ValueError:
                        human_turn = False
                else:
                    human_turn = self._is_human_turn(self.latest_white_to_move)
                if not human_turn:
                    agent_log(
                        'web_bridge.py:_on_snapshot',
                        'auto_move snapshot ignored (robot turn)',
                        {'uci': uci, 'fen_before_hint': fen_before_hint, 'fen_after': msg.fen},
                        hypothesis_id='B',
                    )
                    return
                agent_log(
                    'web_bridge.py:_on_snapshot',
                    'auto_move snapshot scheduled',
                    {'uci': uci, 'fen_before_hint': fen_before_hint, 'fen_after': msg.fen},
                    hypothesis_id='B',
                )
                self._schedule_vision_auto_move(
                    uci,
                    msg.fen,
                    fen_before_hint=fen_before_hint,
                )
            return

        if msg.fen:
            if self._fen_looks_regressed(msg.fen):
                # #region agent log
                agent_log(
                    'web_bridge.py:_on_snapshot',
                    'IGNORE snapshot fen regression',
                    {
                        'incoming_fen': msg.fen,
                        'latest_fen': self.latest_fen,
                        'game_id': game_id,
                        'move_history_len': len(self.move_history),
                    },
                    hypothesis_id='A',
                )
                # #endregion
            else:
                self.latest_fen = msg.fen
                self.latest_white_to_move = bool(msg.white_to_move)
                self.latest_move_number = int(msg.move_number)
        elif msg.white_to_move is not None:
            self.latest_white_to_move = bool(msg.white_to_move)
            self.latest_move_number = int(msg.move_number)
        self._enforce_human_turn_arm_safety()

    def _uci_promo_variants(self, uci: str) -> list[str]:
        uci = (uci or '').strip().lower()
        if len(uci) > 4:
            return [uci]
        return [f'{uci[:4]}{promo}' for promo in ('', 'q', 'r', 'b', 'n')]

    def _undo_move_on_after_board(self, after: chess.Board, uci: str) -> chess.Board | None:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return None
        piece = after.piece_at(move.to_square)
        if piece is None:
            return None
        board = after.copy()
        board.remove_piece_at(move.to_square)
        rank = chess.square_rank(move.from_square)

        if board.is_en_passant(move):
            cap_sq = chess.square(
                chess.square_file(move.to_square),
                rank + (1 if piece.color == chess.WHITE else -1),
            )
            board.set_piece_at(move.from_square, chess.Piece(chess.PAWN, piece.color))
            board.set_piece_at(cap_sq, chess.Piece(chess.PAWN, not piece.color))
            board.turn = not after.turn
            return board
        elif board.is_castling(move):
            board.set_piece_at(move.from_square, piece)
            if move.to_square == chess.square(6, rank):
                rook = board.remove_piece_at(chess.square(5, rank))
                if rook is not None:
                    board.set_piece_at(chess.square(7, rank), rook)
            elif move.to_square == chess.square(2, rank):
                rook = board.remove_piece_at(chess.square(3, rank))
                if rook is not None:
                    board.set_piece_at(chess.square(0, rank), rook)
            board.turn = not after.turn
            return board
        else:
            if move.promotion:
                board.set_piece_at(move.from_square, chess.Piece(chess.PAWN, piece.color))
            else:
                board.set_piece_at(move.from_square, piece)
            board.turn = not after.turn
            resolved = resolve_legal_uci_full(uci, board.fen())
            if resolved:
                try:
                    check = chess.Board(board.fen())
                    check.push_uci(resolved)
                    if check.board_fen() == after.board_fen() and check.turn == after.turn:
                        return board
                except ValueError:
                    pass

            board.remove_piece_at(move.from_square)
            cap_color = not piece.color
            for piece_type in (chess.PAWN, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
                board.set_piece_at(move.from_square, piece)
                board.set_piece_at(move.to_square, chess.Piece(piece_type, cap_color))
                board.turn = not after.turn
                resolved = resolve_legal_uci_full(uci, board.fen())
                if not resolved:
                    board.remove_piece_at(move.to_square)
                    continue
                try:
                    check = chess.Board(board.fen())
                    check.push_uci(resolved)
                    if check.board_fen() == after.board_fen() and check.turn == after.turn:
                        return board
                except ValueError:
                    pass
                board.remove_piece_at(move.to_square)
            return None

    def _fen_before_player_move(
        self,
        fen_after: str,
        uci: str,
        *,
        fen_before_hint: str | None = None,
    ) -> str | None:
        fen_after = (fen_after or '').strip()
        hint = (fen_before_hint or '').strip()
        if hint:
            resolved = resolve_legal_uci_full(uci, hint)
            if resolved:
                try:
                    trial = chess.Board(hint)
                    trial.push_uci(resolved)
                    after = chess.Board(fen_after)
                    if trial.fen() == fen_after or (
                        trial.board_fen() == after.board_fen() and trial.turn == after.turn
                    ):
                        return hint
                except ValueError:
                    pass

        after = chess.Board(fen_after)
        for cand_uci in self._uci_promo_variants(uci):
            before = self._undo_move_on_after_board(after, cand_uci)
            if before is None:
                continue
            fen_before = before.fen()
            resolved = resolve_legal_uci_full(cand_uci, fen_before)
            if resolved is None:
                continue
            try:
                check = chess.Board(fen_before)
                check.push_uci(resolved)
            except ValueError:
                continue
            if check.board_fen() == after.board_fen() and check.turn == after.turn:
                return fen_before
        return None

    def _vision_auto_move_ready(self) -> bool:
        if self._board_reset_in_progress or self._restore_in_progress or not self._active_game_id:
            return False
        if self.game_phase != 'playing':
            return False
        if self._bot_busy or self._hand_confirm_in_progress:
            return False
        with self._hand_lock:
            if self._hand_in_board or self._hand_raw_in_board:
                return False
        return True

    def _schedule_vision_auto_move(
        self,
        uci: str,
        fen_after: str,
        *,
        fen_before_hint: str = '',
    ) -> None:
        uci = (uci or '').strip()
        fen_after = (fen_after or '').strip()
        if not uci or not fen_after:
            return
        with self._auto_move_lock:
            self._pending_vision_auto_move = (uci, fen_after, (fen_before_hint or '').strip())
        self._try_process_pending_vision_auto_move()

    def _try_process_pending_vision_auto_move(self) -> None:
        with self._auto_move_lock:
            pending = self._pending_vision_auto_move
            if pending is None or self._vision_auto_move_in_progress:
                return
            uci, fen_after, fen_before_hint = pending
        if not self._vision_auto_move_ready():
            return
        cooldown = float(self.get_parameter('hand_confirm_cooldown_sec').value)
        with self._auto_move_lock:
            if (
                uci == self._last_auto_move_uci
                and time.time() - self._last_auto_move_at < cooldown
            ):
                if self._is_robot_turn(self.latest_white_to_move) and not self._bot_busy:
                    self._maybe_resume_bot_after_player_move()
                else:
                    self._pending_vision_auto_move = None
                return
            self._vision_auto_move_in_progress = True

        def _run() -> None:
            success = False
            try:
                success = self._handle_vision_auto_move(
                    uci,
                    fen_after,
                    fen_before_hint=fen_before_hint,
                )
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'vision auto move failed: {exc}')
            finally:
                with self._auto_move_lock:
                    self._vision_auto_move_in_progress = False
                    if success:
                        self._last_auto_move_uci = uci
                        self._last_auto_move_at = time.time()
                        self._pending_vision_auto_move = None
                if success:
                    self._maybe_resume_bot_after_player_move()

        threading.Thread(target=_run, daemon=True, name='vision_auto_move').start()

    def _maybe_resume_bot_after_player_move(self) -> None:
        """Retry bot reply when vision detected a move but the arm never started."""
        if not self._bot_session_active:
            return
        if self._board_reset_in_progress:
            return
        if not self._active_game_id:
            return
        if self.game_phase != 'playing' or not self._auto_bot_move():
            return
        self._recover_stale_bot_activity()
        if self._bot_busy or self.bot_status in ('thinking', 'moving', 'paused', 'error'):
            return
        if self._hand_safety_paused:
            return
        with self._hand_lock:
            if self._hand_in_board or self._hand_raw_in_board:
                return
        if not self._is_robot_turn(self.latest_white_to_move):
            return
        if not self._bot_fen_trustworthy(self.latest_fen):
            return
        with self._auto_move_lock:
            if self._pending_vision_auto_move is not None:
                return
        cooldown = float(self.get_parameter('hand_confirm_cooldown_sec').value)
        if time.time() - self._last_bot_resume_attempt_at < cooldown:
            return
        self._last_bot_resume_attempt_at = time.time()
        self.get_logger().info(
            f'resuming bot move after player turn (fen={self.latest_fen[:32]}...)'
        )
        self._maybe_play_bot_move(self.latest_fen)

    def _handle_vision_auto_move(
        self,
        uci: str,
        fen_after: str,
        *,
        fen_before_hint: str = '',
    ) -> bool:
        fen_after = (fen_after or '').strip()
        if not fen_after:
            return False
        fen_before = self._fen_before_player_move(
            fen_after,
            uci,
            fen_before_hint=fen_before_hint,
        )
        if not fen_before:
            self.get_logger().warn(f'vision auto move: cannot infer fen_before for {uci}')
            agent_log(
                'web_bridge.py:_handle_vision_auto_move',
                'fen_before inference failed',
                {'uci': uci, 'fen_after': fen_after, 'fen_before_hint': fen_before_hint},
                hypothesis_id='B',
            )
            return False
        try:
            human_turn = self._is_human_turn(chess.Board(fen_before).turn == chess.WHITE)
        except ValueError:
            human_turn = False
        if not human_turn:
            self.get_logger().warn(f'vision auto move: not human turn for {uci}')
            agent_log(
                'web_bridge.py:_handle_vision_auto_move',
                'rejected robot turn',
                {'uci': uci, 'fen_before': fen_before},
                hypothesis_id='B',
            )
            return False
        legal = resolve_legal_uci_full(uci, fen_before)
        if legal is None:
            self.get_logger().warn(f'vision auto move: illegal uci {uci} on {fen_before}')
            return False
        if not self._uci_is_human_move(fen_before, legal):
            self.get_logger().warn(f'vision auto move: not human piece {uci}')
            agent_log(
                'web_bridge.py:_handle_vision_auto_move',
                'not human piece',
                {
                    'uci': uci,
                    'legal': legal,
                    'fen_before': fen_before,
                    'human_color': self._human_color(),
                },
                hypothesis_id='B',
            )
            return False

        agent_log(
            'web_bridge.py:_handle_vision_auto_move',
            'applying auto move',
            {'uci': legal, 'fen_before': fen_before, 'fen_after': fen_after},
            hypothesis_id='B',
        )

        from_sq, to_sq = legal[:2], legal[2:4]
        self.get_logger().info(f'vision auto move: {from_sq}->{to_sq} ({legal})')
        self.latest_from = from_sq
        self.latest_to = to_sq
        self._sync_from_fen(fen_after)

        self._ensure_active_game()
        board = chess.Board(fen_before)
        move = chess.Move.from_uci(legal)
        captured = captured_piece_symbol(board, move) or ''

        try:
            self._push_undo_snapshot(fen_before, legal, by_robot=False)
            self._record_capture(
                fen_before,
                legal,
                by_robot=False,
                captured_symbol=captured or None,
            )
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'vision auto move capture record failed: {exc}')

        try:
            self._process_player_move_feedback(fen_before, legal)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'vision auto move feedback failed: {exc}')

        promo = promotion_piece_char(move)
        if promo:
            self.promotion_notice = promotion_notice(from_sq, to_sq, promo)

        self.latest_message = f'수 인지됨: {from_sq} → {to_sq}'
        self._spin_for_updates(3)
        self._update_game_over_state(fen_after)
        self.is_check = chess.Board(fen_after).is_check()
        if self.game_phase != 'finished':
            self._recover_stale_bot_activity()
            self._maybe_play_bot_move(fen_after)
        self._persist_game_state()
        return True

    def _maybe_play_bot_move(self, fen: str, *, trust_fen: bool = False) -> None:
        if not self._bot_session_active:
            return
        if not trust_fen and not self._bot_fen_trustworthy(fen):
            return
        parts = fen.split()
        white_to_move = len(parts) > 1 and parts[1] == 'w'
        if self._is_human_turn(white_to_move):
            self._enforce_human_turn_arm_safety()
            return
        self._recover_stale_bot_activity()
        if self.game_phase == 'finished':
            self.get_logger().info('bot move skipped: game finished')
            return
        if not fen or not self._auto_bot_move():
            self.get_logger().info(
                f'bot move skipped: fen={bool(fen)} auto_bot={self._auto_bot_move()}'
            )
            return
        parts = fen.split()
        white_to_move = len(parts) > 1 and parts[1] == 'w'
        if not self._is_robot_turn(white_to_move):
            self.get_logger().info(
                f'bot move skipped: not robot turn (white_to_move={white_to_move})'
            )
            return
        if self._hand_blocks_robot():
            self.get_logger().info('bot move skipped: hand on board')
            return
        if self.bot_status in ('thinking', 'moving', 'paused', 'error') or self._hand_safety_paused:
            self.get_logger().info('bot move skipped: bot active or safety paused')
            return
        with self._bot_lock:
            if self._bot_busy:
                self.get_logger().warn('bot move skipped: bot busy')
                return
            if fen == self._bot_pending_fen:
                self.get_logger().warn('bot move skipped: duplicate pending FEN')
                return
            self._bot_busy = True
            self._bot_pending_fen = fen
        # #region agent log
        agent_log(
            'web_bridge.py:_maybe_play_bot_move',
            'START bot worker',
            {
                'fen': fen,
                'latest_fen': self.latest_fen,
                'human_color': self._human_color(),
                'white_to_move_param': white_to_move,
                'latest_white_to_move': self.latest_white_to_move,
                'bot_status': self.bot_status,
            },
            hypothesis_id='A',
        )
        # #endregion

        def worker() -> None:
            try:
                self._run_bot_move(fen)
            finally:
                with self._bot_lock:
                    self._bot_busy = False
                    self._bot_pending_fen = ''
                if self._bot_worker_thread is threading.current_thread():
                    self._bot_worker_thread = None

        self._bot_cancel_requested = False
        thread = threading.Thread(target=worker, daemon=True, name='bot_move_worker')
        self._bot_worker_thread = thread
        thread.start()

    def _robot_action_ready(self) -> bool:
        return self.action_client.wait_for_server(timeout_sec=0.5)

    def _run_bot_move(self, fen: str) -> None:
        if self._bot_cancel_requested:
            return
        # Defense in depth: _maybe_play_bot_move already checks game_phase/
        # _bot_session_active before spawning this worker thread, but re-check
        # here too — a worker that was already past that check when the game
        # ended (resign, etc.) must not go on to think/move for a game that's
        # already over.
        if self.game_phase == 'finished' or not self._bot_session_active:
            self.bot_status = 'idle'
            return
        try:
            self._bot_activity_started_at = time.time()
            self.bot_status = 'thinking'
            self.latest_message = '로봇이 수를 계산 중...'
            time.sleep(0.1)
            if self._bot_cancel_requested:
                self.bot_status = 'idle'
                return
            if not self._robot_action_ready():
                self.bot_status = 'error'
                self.latest_message = (
                    '로봇 노드 없음 — launch 재시작 필요 (pick_place_node 확인)'
                )
                self.get_logger().error('robot/execute_move action server unavailable')
                return

            active_fen = (self.latest_fen or fen).strip()
            parts = active_fen.split()
            white_to_move = len(parts) > 1 and parts[1] == 'w'
            if not self._is_robot_turn(white_to_move):
                self.get_logger().warn('bot move aborted: not robot turn')
                self.bot_status = 'idle'
                return
            fen = active_fen

            def _configure_and_choose() -> str:
                self._engine.configure_opponent(self._difficulty())
                return self._engine.choose_move(fen)

            # configure + choose must be one locked call: configure_opponent() sends
            # UCI setoption commands on the same subprocess pipe as choose_move()'s
            # position/go commands. Running them as two separate lock acquisitions
            # (or worse, unlocked) let another thread's evaluate()/classify_move()
            # call interleave mid-protocol, corrupting the engine and permanently
            # breaking it (falls back to legal_moves[0] forever afterward — the bot
            # then always develops the same piece and shuffles, regardless of
            # difficulty).
            uci = self._with_engine(_configure_and_choose)
            if uci is None or self._bot_cancel_requested:
                self.bot_status = 'idle'
                return
            if not self._uci_is_robot_move(fen, uci):
                self.get_logger().error(f'bot move aborted: not robot piece {uci}')
                self.bot_status = 'error'
                self.latest_message = f'로봇 기물이 아닌 수: {uci}'
                return
            if self._hand_blocks_robot():
                self.get_logger().warn('bot move deferred: hand on board')
                self.bot_status = 'idle'
                return
            parts = (self.latest_fen or fen).split()
            if len(parts) > 1 and not self._is_robot_turn(parts[1] == 'w'):
                self.get_logger().warn('bot move aborted: turn changed before arm move')
                self.bot_status = 'idle'
                return
            fen = (self.latest_fen or fen).strip()
            from_sq, to_sq = uci[:2], uci[2:4]
            self.get_logger().info(f'Bot move planned: {uci} (fen={fen})')

            self.bot_status = 'moving'
            self.latest_message = f'로봇 이동 중: {from_sq} → {to_sq}'
            success, message = self.execute_bot_move(uci, fen=fen)
            if success:
                self.bot_status = 'idle'
            else:
                self.bot_status = 'error'
                if '보드 UI 반영됨' not in self.latest_message:
                    self.latest_message = f'로봇 수 실패: {message}'
                self.get_logger().error(f'Bot move failed: {message}')
                self._recover_robot_sync_after_failure()
        except Exception as exc:  # noqa: BLE001
            self.bot_status = 'error'
            self.latest_message = f'로봇 수 오류: {exc}'
            self.get_logger().error(f'Bot move error: {exc}')
            self._recover_robot_sync_after_failure()
        finally:
            self._bot_activity_started_at = 0.0
            with self._bot_lock:
                self._bot_busy = False
                self._bot_pending_fen = ''

    def _recover_robot_sync_after_failure(self) -> None:
        """Re-push the current (un-advanced) FEN + graveyard slots to pick_place_node
        after a failed bot move.

        A move that fails partway (e.g. a capture interrupted mid pick-place, or
        the arm rejected/aborted while carrying a piece) can leave pick_place_node's
        internal board/graveyard bookkeeping out of sync with reality, so every
        subsequent move keeps failing the same way. Manually using "보드 수정" and
        saving always fixed this because correct_board() re-syncs robot state as a
        side effect — do that same resync automatically instead of requiring the
        user to intervene by hand every time.

        Rate-limited: _sync_robot_board's CLI-first path spawns a whole new
        `ros2 service call` subprocess. If bot moves keep failing back-to-back
        (the exact scenario this exists for), calling it on every single failure
        can pile up overlapping subprocess/service calls against the same
        /robot/set_board service and starve out unrelated callers (e.g. the
        board-restore button's own pre-restore sync) instead of helping.
        """
        cooldown = 3.0
        now = time.time()
        if now - self._last_recovery_sync_at < cooldown:
            return
        self._last_recovery_sync_at = now
        try:
            sync_ok, sync_msg = self._sync_robot_board(self.latest_fen)
            if not sync_ok:
                self.get_logger().warn(f'post-failure robot resync failed: {sync_msg}')
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'post-failure robot resync raised: {exc}')

    def _apply_board_state_msg(self, board_state: BoardState) -> None:
        if board_state.occupancy.cells:
            self.latest_occupancy = list(board_state.occupancy.cells)
        if board_state.message:
            self.latest_message = board_state.message

    def _sync_from_fen(self, fen: str) -> None:
        self.latest_fen = fen
        self.latest_occupancy = occupancy_from_fen(fen)
        parts = fen.split()
        if len(parts) >= 2:
            self.latest_white_to_move = parts[1] == 'w'
        self._enforce_human_turn_arm_safety()

    def _sync_from_apply_result(self, apply_result) -> None:
        if getattr(apply_result, 'fen', ''):
            self._sync_from_fen(apply_result.fen)
        elif apply_result.board_state is not None and apply_result.board_state.occupancy.cells:
            self.latest_occupancy = list(apply_result.board_state.occupancy.cells)
        if apply_result.board_state is not None and apply_result.board_state.message:
            self.latest_message = apply_result.board_state.message

    def _on_board(self, msg: BoardState) -> None:
        self._apply_board_state_msg(msg)

    def _on_live_occupancy(self, msg: BoardState) -> None:
        # Camera preview only — do not drive the chess UI grid (hand/depth noise).
        del msg

    def _store_preview_jpeg(self, msg: Image) -> None:
        try:
            frame = self._preview_bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return
            with self._preview_lock:
                self._preview_jpeg = encoded.tobytes()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'preview frame convert failed: {exc}', throttle_duration_sec=5.0)

    def _on_preview_image(self, msg: Image) -> None:
        self._preview_annotated_at = time.time()
        self._store_preview_jpeg(msg)

    def _on_fallback_camera(self, msg: Image) -> None:
        if time.time() - self._preview_annotated_at < 2.0:
            return
        self._store_preview_jpeg(msg)

    def get_preview_jpeg(self) -> bytes | None:
        with self._preview_lock:
            return self._preview_jpeg

    def _fill_chess_move(self, msg: ChessMove, fen: str, uci: str) -> str:
        legal = resolve_legal_uci_full(uci, fen)
        if legal is None:
            raise ValueError(f'illegal move {uci!r}')
        board = chess.Board(fen)
        move = chess.Move.from_uci(legal)
        flags = move_physics_flags(board, move)

        msg.from_square.col = chess.square_file(move.from_square)
        msg.from_square.row = chess.square_rank(move.from_square)
        msg.to_square.col = chess.square_file(move.to_square)
        msg.to_square.row = chess.square_rank(move.to_square)
        msg.promotion = str(flags.get('promotion') or '')
        msg.is_capture = bool(flags['is_capture'])
        msg.is_en_passant = bool(flags['is_en_passant'])
        msg.is_castling = bool(flags['is_castling'])

        cap_name = flags.get('capture_square')
        if isinstance(cap_name, str):
            cap_sq = chess.parse_square(cap_name)
            msg.capture_square.col = chess.square_file(cap_sq)
            msg.capture_square.row = chess.square_rank(cap_sq)
        else:
            msg.capture_square = Square(col=255, row=255)

        rook_from = flags.get('rook_from')
        rook_to = flags.get('rook_to')
        if isinstance(rook_from, str) and isinstance(rook_to, str):
            rf = chess.parse_square(rook_from)
            rt = chess.parse_square(rook_to)
            msg.rook_from.col = chess.square_file(rf)
            msg.rook_from.row = chess.square_rank(rf)
            msg.rook_to.col = chess.square_file(rt)
            msg.rook_to.row = chess.square_rank(rt)
        else:
            msg.rook_from = Square(col=255, row=255)
            msg.rook_to = Square(col=255, row=255)
        return legal

    def _update_game_over_state(self, fen: str) -> None:
        outcome = game_outcome(chess.Board(fen))
        self.is_check = chess.Board(fen).is_check()
        if not outcome.is_over:
            return
        self.game_phase = 'finished'
        self.game_result = outcome.reason or 'draw'
        if outcome.winner_side == 'draw':
            self.winner = 'draw'
        elif outcome.winner_side == self._human_color():
            self.winner = 'human'
        else:
            self.winner = 'robot'
        self._set_bot_banter(
            react_to_game_over(
                self._difficulty(),
                result=self.game_result,
                winner=self.winner,
            )
        )
        self._persist_game_state()

    def _human_won(self) -> bool:
        return self.winner == 'human'

    def _normalize_graveyard_slots(self, slots: list[str | None] | None) -> list[str | None]:
        normalized = list(slots or [])
        if len(normalized) < 16:
            normalized.extend([None] * (16 - len(normalized)))
        return normalized[:16]

    def _record_capture(
        self,
        fen_before: str,
        uci: str,
        *,
        by_robot: bool,
        captured_symbol: str | None = None,
    ) -> None:
        try:
            symbol = resolve_capture_symbol(fen_before, uci, captured_symbol)
            if not symbol:
                return
            captured = chess.Piece.from_symbol(symbol)
            human_is_white = self._human_color() == 'white'
            piece_is_white = captured.color == chess.WHITE
            capturer_is_white = not human_is_white if by_robot else human_is_white
            if piece_is_white == capturer_is_white:
                return
            if by_robot:
                self.robot_captures.append(symbol)
                self.graveyard_slots = self._normalize_graveyard_slots(self.graveyard_slots)
                try:
                    self.graveyard_slots = place_in_graveyard(
                        self.graveyard_slots,
                        robot_graveyard_side(self._human_color()),
                        symbol,
                    )
                except ValueError:
                    self.get_logger().warn('robot graveyard full while recording capture')
            else:
                self.human_captures.append(symbol)
                self.human_graveyard_slots = self._normalize_graveyard_slots(
                    self.human_graveyard_slots
                )
                try:
                    self.human_graveyard_slots = place_in_graveyard(
                        self.human_graveyard_slots,
                        human_graveyard_side(self._human_color()),
                        symbol,
                    )
                except ValueError:
                    self.get_logger().warn('human graveyard full while recording capture')
            self._persist_game_state()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'failed to record capture for {uci}: {exc}')

    def get_board_payload(self) -> dict[str, Any]:
        self._maybe_restore_saved_game_once()
        payload: dict[str, Any] = {
            'fen': self.latest_fen,
            'occupancy': self.latest_occupancy,
            'message': self.latest_message,
            'white_to_move': self.latest_white_to_move,
            'human_color': self._human_color(),
            'robot_color': self._robot_color(),
            'board_orientation': self._board_orientation(),
            'bot_status': self.bot_status,
            'user_stop_pending': self._user_stop_pending,
            'last_bot_move': self.last_bot_move,
            'auto_bot_move': self._auto_bot_move(),
            'human_captures': list(self.human_captures),
            'robot_captures': list(self.robot_captures),
            'difficulty': self._difficulty(),
            'move_history': list(self.move_history),
            'eval_cp': self.eval_cp,
            'bot_message': self.bot_message,
            'bot_speech_kind': self.bot_speech_kind,
            'bot_profile': self._bot_profile_payload(),
            'game_phase': self.game_phase,
            'game_result': self.game_result,
            'winner': self.winner,
            'is_check': self.is_check,
            'promotion_notice': self.promotion_notice,
            'game_id': self._active_game_id,
            'graveyard_slots': list(self.graveyard_slots),
            'human_graveyard_slots': list(self.human_graveyard_slots),
            'undo_available': bool(self._undo_snapshots) and self.game_phase == 'playing',
            'promotion_required': self._pending_promotion is not None,
        }
        if self.latest_from and self.latest_to:
            payload['from'] = self.latest_from
            payload['to'] = self.latest_to
        if self._latest_twin_report is not None:
            payload['twin_report'] = self._latest_twin_report
        payload['twin_available'] = self._twin_enabled()
        payload['twin_runtime_enabled'] = self.is_twin_runtime_enabled()
        payload['hand_available'] = self._hand_enabled()
        payload['hand_auto_confirm_enabled'] = self._hand_auto_confirm_runtime
        payload['hand_safety_enabled'] = self._hand_safety_runtime
        return payload

    def attach_executor(self, executor: MultiThreadedExecutor) -> None:
        self._executor = executor

    def _wait_future(self, future, timeout_sec: float) -> bool:
        """Wait for an rclpy future; executor pump timer processes the response."""
        deadline = time.time() + timeout_sec
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        return future.done()

    def _wait_for_service(self, client, timeout_sec: float = 15.0) -> bool:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if client.service_is_ready():
                return True
            time.sleep(0.05)
        return client.service_is_ready()

    def _call_service(self, client, request, timeout_sec: float = 60.0):
        with self._service_call_lock:
            if not self._wait_for_service(client, timeout_sec=15.0):
                return None, 'service unavailable'
            future = client.call_async(request)
            if not self._wait_future(future, timeout_sec):
                return None, f'service call timed out after {timeout_sec}s'
            if future.result() is None:
                return None, 'service call failed'
            return future.result(), ''

    def _call_service_cli(
        self,
        service: str,
        srv_type: str,
        *,
        timeout_sec: float = 60.0,
        yaml_payload: str = '{}',
    ) -> tuple[bool, str]:
        """Fallback ROS service call via ros2 CLI (avoids HTTP-thread executor deadlocks)."""
        env_script = Path.home() / 'Rokey-A-1-cobot2' / 'chess_project_env.sh'
        cmd = (
            f'source "{env_script}" && '
            f'timeout {max(5, int(timeout_sec))} '
            f'ros2 service call {service} {srv_type} "{yaml_payload}"'
        )
        try:
            proc = subprocess.run(
                ['bash', '-lc', cmd],
                capture_output=True,
                text=True,
                timeout=timeout_sec + 5.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f'service cli timed out after {timeout_sec}s'
        output = '\n'.join(part for part in (proc.stdout, proc.stderr) if part).strip()
        if proc.returncode != 0:
            return False, output or f'service cli exit {proc.returncode}'
        if 'success=True' in output.replace(' ', ''):
            return True, output
        if 'success=False' in output.replace(' ', ''):
            return False, output
        return True, output

    def _spin_for_updates(self, count: int = 10) -> None:
        time.sleep(max(0.05, count * 0.05))

    def _reset_hand_tracking(self) -> None:
        if self._hand_service is not None:
            self._hand_service.tracker.reset()
        with self._hand_lock:
            self._hand_in_board = False
            self._hand_raw_in_board = False
            self._hand_seen = False
            self._hand_present = False
            self._hand_raw_in_board_prev = False
            self._hand_raw_streak = 0
            self._hand_safety_paused = False
            self._hand_left_at = 0.0
            self._hand_confirm_pending = False
            self._hand_confirm_in_progress = False
        with self._auto_move_lock:
            self._last_auto_move_uci = ''
            self._last_auto_move_at = 0.0
            self._pending_vision_auto_move = None
            self._vision_auto_move_in_progress = False
        self._publish_hand_in_board(False)

    def _cancel_active_robot_goals(self) -> None:
        for handle in (self._active_move_goal_handle, self._active_restore_goal_handle):
            if handle is None:
                continue
            try:
                cancel_future = handle.cancel_goal_async()
                self._wait_future(cancel_future, 3.0)
            except Exception:  # noqa: BLE001
                pass
        self._active_move_goal_handle = None
        self._active_restore_goal_handle = None

    def _prepare_robot_for_reset(self) -> None:
        """Clear hand pause / in-flight arm goals so reset_board can finish quickly."""
        self._bot_cancel_requested = True
        self._cancel_active_robot_goals()
        with self._bot_lock:
            self._bot_pending_fen = ''
        worker = self._bot_worker_thread
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=12.0)
        with self._bot_lock:
            self._bot_busy = False
        self._bot_worker_thread = None
        self._bot_cancel_requested = False
        self.bot_status = 'idle'
        self._hand_safety_paused = False
        self._publish_hand_in_board(False, force=True)

    def reset_board(self) -> tuple[bool, str]:
        self.get_logger().info('reset_board: start')
        self._board_reset_in_progress = True
        try:
            return self._reset_board_impl()
        finally:
            self._board_reset_in_progress = False

    def _reset_board_impl(self) -> tuple[bool, str]:
        self._reset_hand_tracking()
        self._prepare_robot_for_reset()
        self.get_logger().info('reset_board: robot prepared')
        self.human_captures = []
        self.robot_captures = []
        self.move_history = []
        self._ply_counter = 0
        self.graveyard_slots = [None] * 16
        self.human_graveyard_slots = [None] * 16
        self._undo_snapshots = []
        self._pending_promotion = None
        self._pending_illegal_move = None
        self.eval_cp = 0
        self._set_bot_banter(greeting(self._difficulty()))
        self.game_phase = 'playing'
        self.game_result = ''
        self.winner = ''
        self.is_check = False
        self.promotion_notice = ''
        self.last_bot_move = ''

        robot_ok, robot_msg = self._reset_robot()
        self.get_logger().info(f'reset_board: robot reset success={robot_ok}')
        if not robot_ok and not self._vision_mode():
            return False, robot_msg
        if not robot_ok:
            self.get_logger().warn(
                f'reset_board: robot reset failed — continuing with vision scan: {robot_msg}'
            )
        # reset_board's own service call reports success=True even when the physical
        # arm failed to home (that's a separate, non-fatal failure from the board's
        # logical reset) — the detail only lives in robot_msg, so it must be carried
        # through to whatever message is ultimately returned below, or the UI just
        # shows a plain "board reset" success with no hint the arm never moved.
        home_warning = robot_msg if '로봇 홈 복귀 실패' in robot_msg else ''
        if not self._vision_mode():
            self._sync_from_fen(START_FEN)
            record = self._game_store.create_new_game(
                fen=self.latest_fen,
                human_color=self._human_color(),
                difficulty=self._difficulty(),
                game_phase='playing',
                bot_message=self.bot_message,
            )
            self._active_game_id = record.id
            self._persist_game_state()
            self._bot_session_active = True
            self._maybe_play_bot_move(self.latest_fen)
            if home_warning:
                self.latest_message = home_warning
                return True, f'{message} ({home_warning})'
            return True, message

        scan_ok, scan_msg = self._run_scan_initial()
        self.get_logger().info(f'reset_board: scan success={scan_ok}')
        if not scan_ok:
            return False, scan_msg
        self.latest_from = ''
        self.latest_to = ''
        self.eval_cp = self._eval_from_human_perspective_safe()
        self._spin_for_updates()
        # pick_place is already reset via chess/reset_board; skip set_board here to
        # avoid blocking game start when the robot service queue is busy.
        record = self._game_store.create_new_game(
            fen=self.latest_fen,
            human_color=self._human_color(),
            difficulty=self._difficulty(),
            game_phase='playing',
            bot_message=self.bot_message,
        )
        self._active_game_id = record.id
        self.graveyard_slots = list(record.graveyard_slots)
        self.human_graveyard_slots = list(record.human_graveyard_slots)
        self._persist_game_state()
        self._bot_session_active = True
        self._maybe_play_bot_move(self.latest_fen)
        sync_ok, sync_msg = self._sync_robot_board(self.latest_fen)
        if not sync_ok:
            self.get_logger().warn(f'reset_board: robot sync failed (non-fatal): {sync_msg}')
        self.get_logger().info('reset_board: complete')
        if home_warning:
            self.latest_message = home_warning
            return scan_ok, f'{scan_msg} ({home_warning})'
        return scan_ok, scan_msg

    def restore_board_physical(self) -> tuple[bool, str]:
        agent_log(
            'web_bridge.py:restore_board_physical',
            'restore requested',
            {
                'latest_fen': self.latest_fen,
                'graveyard_slots': self.graveyard_slots,
                'human_graveyard_slots': self.human_graveyard_slots,
                'game_phase': self.game_phase,
            },
            hypothesis_id='G',
        )
        if not self.restore_action_client.wait_for_server(timeout_sec=5.0):
            return False, 'restore_board action unavailable'

        if self.latest_fen.strip():
            sync_ok, sync_msg = self._sync_robot_board(self.latest_fen)
            agent_log(
                'web_bridge.py:restore_board_physical',
                'robot board sync before restore',
                {'sync_ok': sync_ok, 'sync_msg': sync_msg},
                hypothesis_id='G',
            )
            if not sync_ok:
                return False, sync_msg

        send_future = self.restore_action_client.send_goal_async(RestoreBoard.Goal())
        if not self._wait_future(send_future, 10.0) or send_future.result() is None:
            return False, 'failed to send restore goal'

        goal_handle = send_future.result()
        if not goal_handle.accepted:
            return False, 'restore goal rejected'

        self._restore_in_progress = True
        self._active_restore_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        deadline = time.time() + 600.0
        try:
            while time.time() < deadline:
                if result_future.done():
                    break
                time.sleep(0.05)
            if not result_future.done():
                goal_handle.cancel_goal_async()
                return False, 'restore timed out'

            result = result_future.result().result
            if not result.success:
                return False, result.message
        finally:
            self._restore_in_progress = False
            self._active_restore_goal_handle = None

        if self._vision_mode():
            scan_result, err = self._call_service(
                self.scan_initial_client,
                ScanInitial.Request(),
                timeout_sec=90.0,
            )
            if scan_result is None:
                return False, err
            if scan_result.board_state is not None:
                self._apply_board_state_msg(scan_result.board_state)
            if getattr(scan_result, 'fen', ''):
                self._sync_from_fen(scan_result.fen)
            self._spin_for_updates()

        return True, result.message

    def resign_game(self) -> tuple[bool, str]:
        if self.game_phase == 'finished':
            return False, '게임이 이미 종료되었습니다'
        # Stop any in-flight/queued bot activity immediately — without this, a
        # bot-move worker thread already past its game_phase check (e.g. spawned
        # right as resign happens) or a vision "move" misdetected from unrelated
        # board activity (like a board restore) could still go on to make a move
        # after the game was declared over.
        self._bot_session_active = False
        self._bot_cancel_requested = True
        self._cancel_active_robot_goals()
        if self.bot_status in ('thinking', 'moving'):
            with self._bot_lock:
                self._bot_pending_fen = ''
                self._bot_busy = False
            self.bot_status = 'idle'
        self._bot_cancel_requested = False
        self.game_phase = 'finished'
        self.game_result = 'resign'
        self.winner = 'robot'
        self._set_bot_banter(
            react_to_game_over(
                self._difficulty(),
                result='resign',
                winner='robot',
            )
        )
        self._ensure_active_game()
        self._persist_game_state()
        return True, '기권했습니다'

    @staticmethod
    def _ros_yaml_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _reset_robot(self) -> tuple[bool, str]:
        ok, msg = self._call_service_cli(
            '/chess/reset_board',
            'chess_msgs/srv/ResetBoard',
            timeout_sec=12.0,
        )
        if ok:
            # Don't discard the response — a homing failure (e.g. arm rejected by
            # the DSR controller, timed out) is reported in the service message,
            # not just as a ROS log line. Surface it instead of always showing a
            # blanket "board reset" success with no hint the arm never moved home.
            msg_match = re.search(r"message='([^']*)'", msg)
            return True, msg_match.group(1) if msg_match else 'board reset'
        self.get_logger().warn(f'reset_board cli failed ({msg}); trying rclpy')
        result, err = self._call_service(
            self.reset_client,
            ResetBoard.Request(),
            timeout_sec=6.0,
        )
        if result is not None:
            return bool(result.success), result.message
        hint = (
            '손을 카메라에서 치우고 다시 시도하세요. '
            'pick_place_node가 실행 중인지도 확인하세요 '
            '(scripts/stop_chess_stack.sh 후 launch 재시작)'
        )
        if err == 'service unavailable' and not ok:
            return False, f'reset service unavailable — {hint}'
        return False, msg or err or f'reset call failed — {hint}'

    def _run_scan_initial(self) -> tuple[bool, str]:
        ok, cli_out = self._call_service_cli(
            '/chess/scan_initial',
            'chess_msgs/srv/ScanInitial',
            timeout_sec=45.0,
        )
        if ok:
            fen_match = re.search(r"fen='([^']+)'", cli_out)
            msg_match = re.search(r"message='([^']*)'", cli_out)
            if fen_match:
                self._sync_from_fen(fen_match.group(1))
            message = msg_match.group(1) if msg_match else cli_out
            return True, message
        self.get_logger().warn(f'scan_initial cli failed ({cli_out}); trying rclpy')
        result, err = self._call_service(
            self.scan_initial_client,
            ScanInitial.Request(),
            timeout_sec=20.0,
        )
        if result is not None:
            if result.board_state is not None:
                self._apply_board_state_msg(result.board_state)
            if getattr(result, 'fen', ''):
                self._sync_from_fen(result.fen)
            return bool(result.success), result.message
        return False, cli_out or err or 'scan_initial failed'

    def _sync_robot_board(self, fen: str) -> tuple[bool, str]:
        """Sync pick_place_node internal FEN/occupancy with the logical game state."""
        fen = (fen or '').strip()
        if not fen:
            return False, 'empty FEN for robot sync'
        gy_json = json.dumps(self.graveyard_slots)
        human_gy_json = json.dumps(self.human_graveyard_slots)
        human_color = self._human_color()
        board_orientation = self._board_orientation()
        yaml_payload = (
            '{'
            f'fen: {self._ros_yaml_quote(fen)}, '
            f'graveyard_slots_json: {self._ros_yaml_quote(gy_json)}, '
            f'human_graveyard_slots_json: {self._ros_yaml_quote(human_gy_json)}, '
            f'human_color: {self._ros_yaml_quote(human_color)}, '
            f'board_orientation: {self._ros_yaml_quote(board_orientation)}'
            '}'
        )
        ok, cli_out = self._call_service_cli(
            '/robot/set_board',
            'chess_msgs/srv/SetBoard',
            timeout_sec=8.0,
            yaml_payload=yaml_payload,
        )
        if ok:
            return True, cli_out or 'robot board synced'
        self.get_logger().warn(f'robot/set_board cli failed ({cli_out}); trying rclpy')
        request = SetBoard.Request(fen=fen)
        request.graveyard_slots_json = gy_json
        request.human_graveyard_slots_json = human_gy_json
        request.human_color = human_color
        request.board_orientation = board_orientation
        result, err = self._call_service(
            self.robot_set_board_client,
            request,
            timeout_sec=15.0,
        )
        if result is None:
            return False, f'robot board sync failed: {cli_out or err}'
        if not result.success:
            return False, f'robot board sync failed: {result.message}'
        return True, result.message

    def confirm_player_move(
        self,
        *,
        promotion_piece: str = '',
        from_square: str = '',
        to_square: str = '',
    ) -> tuple[bool, str, str, str]:
        if self.game_phase == 'finished':
            return False, '게임이 종료되었습니다', '', ''

        if self.bot_status == 'error':
            self.bot_status = 'idle'
            with self._bot_lock:
                self._bot_pending_fen = ''
                self._bot_busy = False

        if not self._is_human_turn(self.latest_white_to_move):
            return False, '지금은 로봇 차례입니다', '', ''

        fen_before = self.latest_fen
        request = ConfirmPlayerMove.Request()
        if promotion_piece:
            request.promotion_piece = promotion_piece.strip().lower()
            request.from_square = from_square or (self._pending_promotion or {}).get('from', '')
            request.to_square = to_square or (self._pending_promotion or {}).get('to', '')

        result, err = self._call_service(
            self.confirm_player_client,
            request,
            timeout_sec=90.0,
        )
        if result is None:
            return False, err, '', ''

        if getattr(result, 'promotion_required', False) or result.message == 'promotion_required':
            self._pending_promotion = {
                'from': result.from_square,
                'to': result.to_square,
                'fen_before': fen_before,
            }
            self.latest_from = result.from_square
            self.latest_to = result.to_square
            self.latest_message = '승격할 기물을 선택하세요'
            return False, self.latest_message, result.from_square, result.to_square

        self._pending_promotion = None
        self.latest_from = result.from_square
        self.latest_to = result.to_square
        uci = getattr(result, 'uci', '') or (
            f'{result.from_square}{result.to_square}'
            if result.from_square and result.to_square
            else ''
        )
        legal = bool(uci) and self._is_legal_uci(fen_before, uci)
        human_move = bool(uci) and self._uci_is_human_move(fen_before, uci)
        success = bool(result.success) and legal and human_move
        agent_log(
            'web_bridge.py:confirm_player_move',
            'confirm result',
            {
                'success': success,
                'legal': legal,
                'human_move': human_move,
                'uci': uci,
                'fen_before': fen_before,
                'message': result.message,
            },
            hypothesis_id='C',
        )
        bot_fen = ''

        if self._is_illegal_move_result(result, legal=legal, uci=uci):
            from_sq = (
                getattr(result, 'from_square', '') or (uci[:2] if len(uci) >= 4 else '')
            ).strip().lower()
            to_sq = (
                getattr(result, 'to_square', '') or (uci[2:4] if len(uci) >= 4 else '')
            ).strip().lower()
            if from_sq and to_sq:
                self._pending_illegal_move = {'from': from_sq, 'to': to_sq}
                self.latest_from = from_sq
                self.latest_to = to_sq
                self._set_bot_banter(
                    react_to_illegal_move(
                        self._difficulty(),
                        from_sq=from_sq,
                        to_sq=to_sq,
                    )
                )
                self.latest_message = result.message or f'불법 수입니다: {from_sq} → {to_sq}'
                if result.board_state is not None:
                    self._apply_board_state_msg(result.board_state)
                self._spin_for_updates()
                self._persist_game_state()
                return False, self.latest_message, from_sq, to_sq

        if success and uci:
            self._pending_illegal_move = None
            self._ensure_active_game()
            try:
                self._push_undo_snapshot(fen_before, uci, by_robot=False)
                captured = getattr(result, 'captured_piece', '') or ''
                self._record_capture(
                    fen_before,
                    uci,
                    by_robot=False,
                    captured_symbol=captured or None,
                )
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'capture record raised unexpectedly: {exc}')
            try:
                self._process_player_move_feedback(fen_before, uci)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'player move feedback failed: {exc}')
            promo = getattr(result, 'promotion_piece', '') or ''
            if promo:
                self.promotion_notice = promotion_notice(
                    result.from_square,
                    result.to_square,
                    promo,
                )
        elif result.success and legal and not human_move:
            self.latest_message = f'사용자 기물이 아닌 수입니다: {uci or "unknown"}'
            self.get_logger().warn(
                f'vision move wrong piece color: {uci} (fen={fen_before})'
            )
        elif result.success and not legal:
            self.latest_message = f'불법 수입니다: {uci or "unknown"}'
            self.get_logger().warn(
                f'vision move not legal on board: {uci} (fen={fen_before})'
            )

        if success and getattr(result, 'fen', ''):
            self._sync_from_fen(result.fen)
            bot_fen = self.latest_fen
        elif success and result.board_state is not None:
            self._apply_board_state_msg(result.board_state)
            bot_fen = self.latest_fen
        elif not success and result.board_state is not None:
            self._apply_board_state_msg(result.board_state)

        self._spin_for_updates(3)
        if success and bot_fen:
            sync_ok, sync_msg = self._sync_robot_board(bot_fen)
            if not sync_ok:
                self.get_logger().warn(
                    f'robot board sync after player move failed: {sync_msg}'
                )
            self._update_game_over_state(bot_fen)
            self.is_check = chess.Board(bot_fen).is_check()
            if self.game_phase != 'finished':
                self._recover_stale_bot_activity()
                self._maybe_play_bot_move(bot_fen)
            else:
                self.get_logger().info('bot move skipped after player move: game finished')

        if not success and 'no move detected' in (result.message or '').lower():
            msg = result.message or ''
            board_unchanged = 'departed=-' in msg and 'arrived=-' in msg
            result_fen = (getattr(result, 'fen', '') or '').strip()
            robot_turn = self._is_robot_turn(self.latest_white_to_move)
            if not robot_turn and result_fen:
                try:
                    robot_turn = self._is_robot_turn(
                        chess.Board(result_fen).turn == chess.WHITE
                    )
                except ValueError:
                    robot_turn = False
            if (
                board_unchanged
                and self.game_phase != 'finished'
                and robot_turn
                and result_fen
                and self._is_robot_turn(chess.Board(result_fen).turn == chess.WHITE)
            ):
                if result_fen:
                    self._sync_from_fen(result_fen)
                self.get_logger().info(
                    'confirm: board already reflects last move; triggering bot'
                )
                self._recover_stale_bot_activity()
                self._maybe_play_bot_move(result_fen or self.latest_fen)
                self._persist_game_state()
                from_sq = getattr(result, 'from_square', '') or ''
                to_sq = getattr(result, 'to_square', '') or ''
                return (
                    True,
                    '이미 반영된 수입니다. 로봇이 응수합니다.',
                    from_sq,
                    to_sq,
                )

        if success or result.success:
            self._persist_game_state()

        message = self.latest_message if not success and not legal else result.message
        if (
            not success
            and self._twin_active()
            and bool(self.get_parameter('twin_auto_on_confirm_fail').value)
        ):
            try:
                twin_payload = self.verify_board_twin(confirm_failed=True, use_fresh_scan=True)
                if not twin_payload.get('aligned', True):
                    message = f'{message} (Reality Check: {twin_payload.get("message", "")})'
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'board twin auto verify failed: {exc}')
        return (
            success,
            message,
            result.from_square,
            result.to_square,
        )

    def confirm_player_promotion(self, piece: str) -> tuple[bool, str, str, str]:
        piece = piece.strip().lower()
        if piece not in {'q', 'r', 'b', 'n'}:
            return False, '승격 기물은 q, r, b, n 중 하나여야 합니다', '', ''
        if not self._pending_promotion:
            return False, '대기 중인 승격 수가 없습니다', '', ''
        from_sq = self._pending_promotion['from']
        to_sq = self._pending_promotion['to']
        return self.confirm_player_move(
            promotion_piece=piece,
            from_square=from_sq,
            to_square=to_sq,
        )

    def correct_board(
        self,
        fen: str,
        *,
        graveyard_slots: list[str | None] | None = None,
        human_graveyard_slots: list[str | None] | None = None,
    ) -> tuple[bool, str]:
        if self.bot_status in ('thinking', 'moving'):
            raise RuntimeError('봇이 동작 중입니다. 잠시 후 다시 시도하세요.')

        fen = fen.strip()
        if not fen:
            raise ValueError('FEN이 비어 있습니다')

        try:
            chess.Board(fen)
        except ValueError as exc:
            raise ValueError(f'잘못된 FEN: {exc}') from exc

        with self._bot_lock:
            self._bot_busy = False
            self._bot_pending_fen = ''
        self.bot_status = 'idle'
        self.promotion_notice = ''
        self._pending_promotion = None
        self._pending_illegal_move = None

        fen_before = self.latest_fen
        if graveyard_slots is not None:
            self.graveyard_slots = list(graveyard_slots)
            # The visible captured-pieces bar reads human_captures/robot_captures
            # (plain symbol lists), not graveyard_slots (physical slot assignment) —
            # without this, editing the graveyard grid saved fine but never showed
            # up anywhere in the UI.
            self.robot_captures = [s for s in self.graveyard_slots if s]
        if human_graveyard_slots is not None:
            self.human_graveyard_slots = list(human_graveyard_slots)
            self.human_captures = [s for s in self.human_graveyard_slots if s]
        else:
            self.graveyard_slots, self.human_graveyard_slots = reconcile_graveyards_with_fen(
                fen_before,
                fen,
                self.graveyard_slots,
                self.human_graveyard_slots,
                robot_side=robot_graveyard_side(self._human_color()),
                human_side=human_graveyard_side(self._human_color()),
            )

        inferred_uci = infer_human_move_uci(fen_before, fen, self._human_color())
        target_fen = fen
        if inferred_uci:
            board = chess.Board(fen_before)
            board.push_uci(inferred_uci)
            target_fen = board.fen()
        else:
            target_fen = guard_correction_fen(fen_before, fen)
            if target_fen != fen:
                self.get_logger().warn(
                    f'correct_board: submitted FEN counters regressed '
                    f'({fen!r} vs {fen_before!r}); keeping trusted move counters'
                )
            try:
                if graveyard_slots is None and human_graveyard_slots is None:
                    self._record_capture(fen_before, inferred_uci, by_robot=False)
                else:
                    symbol = resolve_capture_symbol(fen_before, inferred_uci, None)
                    if symbol and symbol not in self.human_captures:
                        self.human_captures.append(symbol)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'capture record after board correction: {exc}')
            try:
                self._process_player_move_feedback(fen_before, inferred_uci)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'move feedback after board correction: {exc}')

        logical_ok, logical_msg = self._sync_logical_board(target_fen)
        if not logical_ok:
            return False, logical_msg

        sync_ok, sync_msg = self._sync_robot_board(self.latest_fen)
        if not sync_ok:
            self.get_logger().warn(f'robot board sync after correct_board failed: {sync_msg}')

        self._refresh_game_phase(self.latest_fen)
        self.eval_cp = self._eval_from_human_perspective()
        self.latest_from = ''
        self.latest_to = ''
        self._undo_snapshots = []
        self._ensure_active_game()
        if inferred_uci:
            self.latest_message = '보드 정정 후 수가 반영되었습니다.'
        else:
            self.latest_message = '보드가 수동 정정되었습니다. 수 두었음을 다시 시도하세요.'
        self._update_game_over_state(self.latest_fen)
        self.is_check = chess.Board(self.latest_fen).is_check()
        if self.game_phase != 'finished':
            self._maybe_play_bot_move(self.latest_fen, trust_fen=True)
        self._spin_for_updates()
        self._persist_game_state()
        return True, self.latest_message

    def _push_undo_snapshot(self, fen_before: str, uci: str, *, by_robot: bool) -> None:
        self._undo_snapshots.append(
            make_ply_snapshot(
                fen=fen_before,
                graveyard_slots=self.graveyard_slots,
                human_graveyard_slots=self.human_graveyard_slots,
                human_captures=self.human_captures,
                robot_captures=self.robot_captures,
                move_history=self.move_history,
                ply_counter=self._ply_counter,
                uci=uci,
                by_robot=by_robot,
            )
        )

    def _apply_undo_snapshot(self, snap: dict[str, Any]) -> None:
        self._sync_from_fen(str(snap['fen']))
        self.graveyard_slots = list(snap['graveyard_slots'])
        self.human_graveyard_slots = list(snap['human_graveyard_slots'])
        self.human_captures = list(snap['human_captures'])
        self.robot_captures = list(snap['robot_captures'])
        self.move_history = [dict(entry) for entry in snap['move_history']]
        self._ply_counter = int(snap['ply_counter'])
        self.game_phase = 'playing'
        self.game_result = ''
        self.winner = ''
        self.promotion_notice = ''
        self._pending_promotion = None
        self.is_check = chess.Board(self.latest_fen).is_check()
        self.eval_cp = self._eval_from_human_perspective()
        self.latest_from = ''
        self.latest_to = ''
        self.latest_message = '이전 수로 되돌렸습니다'

    def undo_last_turn(self) -> tuple[bool, str]:
        if self.game_phase == 'finished':
            return False, '게임이 종료되었습니다'
        if self.bot_status in ('thinking', 'moving'):
            return False, '봇이 동작 중입니다. 잠시 후 다시 시도하세요.'
        if not self._undo_snapshots:
            return False, '되돌릴 수가 없습니다'

        try:
            target, specs = build_undo_moves_payload(
                self._undo_snapshots,
                current_fen=self.latest_fen,
                current_robot_gy=self.graveyard_slots,
                current_human_gy=self.human_graveyard_slots,
                robot_side=robot_graveyard_side(self._human_color()),
                human_side=human_graveyard_side(self._human_color()),
            )
        except ValueError as exc:
            return False, str(exc)

        undo_count = len(specs)
        request = UndoMoves.Request()
        request.moves_json = json.dumps(specs)
        result, err = self._call_service(self.robot_undo_client, request, timeout_sec=180.0)
        if result is None:
            return False, err or 'undo service unavailable'
        if not result.success:
            return False, result.message or 'undo physical failed'

        self._apply_undo_snapshot(target)
        self._undo_snapshots = self._undo_snapshots[:-undo_count]

        logical_ok, logical_msg = self._sync_logical_board(self.latest_fen)
        if not logical_ok:
            self.get_logger().warn(f'vision sync after undo failed: {logical_msg}')
        sync_ok, sync_msg = self._sync_robot_board(self.latest_fen)
        if not sync_ok:
            self.get_logger().warn(f'robot sync after undo failed: {sync_msg}')

        self._persist_game_state()
        return True, self.latest_message

    def revert_illegal_move(self, from_sq: str, to_sq: str) -> tuple[bool, str]:
        if self.game_phase == 'finished':
            return False, '게임이 종료되었습니다'
        if self.bot_status in ('thinking', 'moving'):
            return False, '봇이 동작 중입니다. 잠시 후 다시 시도하세요.'

        from_sq = from_sq.strip().lower()
        to_sq = to_sq.strip().lower()
        if len(from_sq) != 2 or len(to_sq) != 2:
            return False, '잘못된 칸 좌표입니다'

        fen_before = self.latest_fen
        board = chess.Board(fen_before)
        try:
            to_square = chess.parse_square(to_sq)
        except ValueError:
            return False, f'잘못된 목적 칸: {to_sq}'

        graveyard_pick = None
        captured = board.piece_at(to_square)
        if captured is not None:
            graveyard_pick = find_graveyard_slot_for_symbol(
                self.human_graveyard_slots,
                human_graveyard_side(self._human_color()),
                captured.symbol(),
            )

        payload = [
            {
                'mode': 'physical',
                'fen_before': fen_before,
                'from_square': from_sq,
                'to_square': to_sq,
                'graveyard_pick': graveyard_pick,
            }
        ]
        request = UndoMoves.Request()
        request.moves_json = json.dumps(payload)

        self.bot_status = 'moving'
        self.latest_message = f'불법 수 되돌리는 중: {to_sq} → {from_sq}'
        result, err = self._call_service(self.robot_undo_client, request, timeout_sec=180.0)
        if result is None:
            self.bot_status = 'error'
            return False, err or 'undo service unavailable'
        if not result.success:
            self.bot_status = 'error'
            return False, result.message or 'physical revert failed'

        if graveyard_pick:
            idx = graveyard_slot_index(
                int(graveyard_pick['col']),
                int(graveyard_pick['grave_row']),
            )
            symbol = self.human_graveyard_slots[idx]
            self.human_graveyard_slots[idx] = None
            if symbol and symbol in self.human_captures:
                self.human_captures.remove(symbol)

        logical_ok, logical_msg = self._sync_logical_board(fen_before)
        if not logical_ok:
            self.get_logger().warn(f'vision sync after illegal revert failed: {logical_msg}')
        sync_ok, sync_msg = self._sync_robot_board(fen_before)
        if not sync_ok:
            self.get_logger().warn(f'robot sync after illegal revert failed: {sync_msg}')

        self._pending_illegal_move = None
        self.latest_from = ''
        self.latest_to = ''
        self.bot_status = 'idle'
        self._set_bot_banter(react_to_illegal_move_reverted(self._difficulty()))
        self.latest_message = self.bot_message
        self._spin_for_updates()
        self._persist_game_state()
        return True, self.latest_message

    def _process_player_move_feedback(self, fen_before: str, uci: str) -> None:
        legal = resolve_legal_uci_full(uci, fen_before)
        if legal is None:
            return

        board = chess.Board(fen_before)
        move = chess.Move.from_uci(legal)
        is_capture = board.is_capture(move) or board.is_en_passant(move)
        board.push(move)
        is_check = board.is_check()

        classification = self._with_engine(
            lambda: self._engine.classify_move(fen_before, legal)
        )
        self.eval_cp = self._eval_from_human_perspective()
        self._append_move_history(
            fen_before=fen_before,
            uci=legal,
            color=self._human_color(),
            eval_cp=self.eval_cp,
            quality=classification.quality,
        )
        san = self._uci_to_san(fen_before, legal)
        self._set_bot_banter(
            react_to_player_move(
                self._difficulty(),
                quality=classification.quality,
                is_capture=is_capture,
                is_check=is_check,
                san=san,
            )
        )

    def _process_bot_move_feedback(self, fen_before: str, uci: str) -> None:
        legal = resolve_legal_uci_full(uci, fen_before)
        if legal is None:
            return

        board = chess.Board(fen_before)
        move = chess.Move.from_uci(legal)
        is_capture = board.is_capture(move) or board.is_en_passant(move)
        board.push(move)
        is_check = board.is_check()

        self.eval_cp = self._eval_from_human_perspective()
        self._append_move_history(
            fen_before=fen_before,
            uci=legal,
            color=self._robot_color(),
            eval_cp=self.eval_cp,
        )
        self._set_bot_banter(
            react_to_bot_move(
                self._difficulty(),
                is_capture=is_capture,
                is_check=is_check,
            )
        )
        promo = promotion_piece_char(move)
        if promo:
            self.promotion_notice = promotion_notice(legal[:2], legal[2:4], promo)

    def _apply_robot_move_service(
        self,
        uci: str,
        fen: str,
        *,
        timeout_sec: float = 30.0,
    ) -> tuple[bool, str, object | None]:
        apply_req = ApplyRobotMove.Request()
        apply_req.move = ChessMove()
        legal = self._fill_chess_move(apply_req.move, fen, uci)
        apply_result, err = self._call_service(
            self.apply_robot_client,
            apply_req,
            timeout_sec=timeout_sec,
        )
        if apply_result is None:
            return False, err, None
        if not apply_result.success:
            return False, apply_result.message, apply_result
        self._sync_from_apply_result(apply_result)
        self._spin_for_updates()
        return True, apply_result.message or legal, apply_result

    def _call_trigger_service(self, client, *, timeout_sec: float = 3.0) -> tuple[bool, str]:
        request = Trigger.Request()
        result, err = self._call_service(client, request, timeout_sec=timeout_sec)
        if result is None:
            return False, err or 'service unavailable'
        if not result.success:
            return False, result.message or 'request failed'
        return True, result.message or 'ok'

    def stop_robot_motion(self) -> tuple[bool, str]:
        self._bot_cancel_requested = True
        self._cancel_active_robot_goals()
        ok, msg = self._call_trigger_service(self.robot_user_stop_client)
        if not ok:
            self.get_logger().warn(f'robot/user_stop failed: {msg}')
        self._user_stop_pending = True
        if self.bot_status not in ('stopped',):
            self._bot_status_before_pause = self.bot_status
        self.bot_status = 'stopped'
        with self._bot_lock:
            self._bot_busy = False
            self._bot_pending_fen = ''
        self.latest_message = '로봇 동작이 정지되었습니다'
        self._persist_game_state()
        return True, msg or 'stopped'

    def resume_robot_motion(self) -> tuple[bool, str]:
        ok, msg = self._call_trigger_service(self.robot_user_stop_resume_client)
        if not ok:
            return False, msg
        self._user_stop_pending = False
        self._bot_cancel_requested = False
        self.bot_status = self._bot_status_before_pause or 'idle'
        if self.bot_status == 'stopped':
            self.bot_status = 'idle'
        self.latest_message = '로봇 동작을 재개합니다'
        if (
            self._bot_session_active
            and self.game_phase == 'playing'
            and self._is_robot_turn(self.latest_white_to_move)
        ):
            self._maybe_play_bot_move(self.latest_fen)
        self._persist_game_state()
        return True, msg

    def abort_robot_motion(self) -> tuple[bool, str]:
        self._bot_cancel_requested = True
        self._cancel_active_robot_goals()
        ok, msg = self._call_trigger_service(self.robot_user_stop_abort_client, timeout_sec=20.0)
        self._user_stop_pending = False
        self._recover_stale_bot_activity()
        self.bot_status = 'idle'
        self.latest_message = '로봇 동작을 중단하고 홈으로 복귀했습니다'
        self._persist_game_state()
        return ok, msg or 'aborted'

    def _execute_physical_move(self, uci: str, *, fen: str, for_voice: bool = False) -> tuple[bool, str]:
        """Drive the arm through one physical move.

        Used both for the bot's own automatic moves (default) and for voice
        commands, where the human dictates their own move and the arm executes
        it on their behalf. The turn/piece-color checks below assume a robot
        move unless for_voice is set — a voice move happens *during the
        human's turn* on a *human* piece by definition, so those same checks
        would otherwise always reject it.
        """
        if not self._bot_session_active:
            return False, 'bot session inactive'
        if not for_voice and self._is_human_turn(self.latest_white_to_move):
            self._enforce_human_turn_arm_safety()
            return False, 'not robot turn'
        if self._hand_blocks_robot():
            return False, 'hand on board'
        fen = (self.latest_fen or fen or '').strip()
        parts = fen.split()
        white_to_move = len(parts) > 1 and parts[1] == 'w'
        if not for_voice and not self._is_robot_turn(white_to_move):
            return False, 'not robot turn'
        legal = resolve_legal_uci_full(uci, fen)
        if legal:
            if for_voice:
                if not self._uci_is_human_move(fen, legal):
                    return False, 'not human piece'
            elif not self._uci_is_robot_move(fen, legal):
                return False, 'not robot piece'
        if not self.action_client.wait_for_server(timeout_sec=5.0):
            return False, 'execute_move action unavailable'

        goal = ExecuteMove.Goal()
        goal.move = ChessMove()
        self._fill_chess_move(goal.move, fen, uci)

        if self._hand_blocks_robot():
            return False, 'hand on board'
        parts = (self.latest_fen or fen).split()
        if not for_voice and len(parts) > 1 and not self._is_robot_turn(parts[1] == 'w'):
            return False, 'not robot turn'
        if self._active_move_goal_handle is not None:
            return False, 'move already in progress'

        # #region agent log
        agent_log(
            'web_bridge.py:_execute_physical_move',
            'SEND execute_move goal',
            {
                'uci': uci,
                'fen': fen,
                'latest_fen': self.latest_fen,
                'human_color': self._human_color(),
                'white_to_move_fen': white_to_move,
                'latest_white_to_move': self.latest_white_to_move,
                'is_robot_piece': self._uci_is_robot_move(fen, legal or uci),
            },
            hypothesis_id='D',
        )
        # #endregion
        send_future = self.action_client.send_goal_async(goal)
        if not self._wait_future(send_future, 10.0) or send_future.result() is None:
            return False, 'failed to send goal'

        goal_handle = send_future.result()
        if not goal_handle.accepted:
            return False, 'goal rejected'

        self._active_move_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        deadline = time.time() + 180.0
        try:
            while time.time() < deadline:
                if result_future.done():
                    break
                time.sleep(0.05)
            if not result_future.done():
                goal_handle.cancel_goal_async()
                return False, 'move timed out'

            result = result_future.result().result
            if not result.success:
                return False, result.message
            return True, result.message
        finally:
            self._active_move_goal_handle = None

    def _push_local_fen_move(self, uci: str, *, fen: str) -> bool:
        """Apply a move to local FEN only (fallback when vision_game sync fails)."""
        legal = resolve_legal_uci_full(uci, fen)
        if legal is None:
            return False
        try:
            board = chess.Board(fen)
            board.push_uci(legal)
            self._sync_from_fen(board.fen())
            return True
        except ValueError:
            return False

    def _mark_bot_move_metadata(self, uci: str) -> None:
        self.latest_from = uci[:2]
        self.latest_to = uci[2:4]
        self.last_bot_move = uci

    def execute_bot_move(
        self,
        uci: str,
        *,
        fen: str | None = None,
    ) -> tuple[bool, str]:
        """Move the arm first; update grid and vision_game only after physical success."""
        fen_before = fen or self.latest_fen
        legal = resolve_legal_uci_full(uci, fen_before)
        if legal is None:
            return False, f'illegal bot move: {uci}'
        parts = fen_before.split()
        white_to_move = len(parts) > 1 and parts[1] == 'w'
        if not self._is_robot_turn(white_to_move):
            return False, 'not robot turn'
        if not self._uci_is_robot_move(fen_before, legal):
            return False, f'not robot piece: {legal}'

        sync_ok, sync_msg = self._sync_robot_board(fen_before)
        if not sync_ok:
            return False, sync_msg

        physical_ok, physical_msg = self._execute_physical_move(legal, fen=fen_before)
        if not physical_ok:
            self.latest_message = f'로봇 이동 실패: {physical_msg}'
            return False, physical_msg

        # Arm homed — release UI before logical sync so the human can play.
        self.bot_status = 'idle'
        self._hand_safety_paused = False
        self._publish_hand_in_board(False, force=True)

        logical_synced = False
        if self._vision_mode():
            logical_ok, logical_msg, _ = self._apply_robot_move_service(
                legal,
                fen_before,
                timeout_sec=10.0,
            )
            if logical_ok:
                logical_synced = True
            else:
                self.get_logger().warn(
                    f'vision_game sync failed after arm moved: {logical_msg}; applying local FEN'
                )

        if not logical_synced and not self._push_local_fen_move(legal, fen=fen_before):
            self.latest_message = (
                f'로봇은 이동했으나 보드 상태 반영 실패: {legal[:2]} → {legal[2:4]}'
            )
            return False, 'logical board update failed after physical move'

        self._push_undo_snapshot(fen_before, legal, by_robot=True)
        self._record_capture(fen_before, legal, by_robot=True)
        self._mark_bot_move_metadata(legal)
        self._process_bot_move_feedback(fen_before, legal)
        self.latest_message = f'로봇 수: {legal[:2]} → {legal[2:4]}'
        self._update_game_over_state(self.latest_fen)
        self.is_check = chess.Board(self.latest_fen).is_check()
        self._persist_game_state()
        return True, physical_msg

    def execute_move(self, from_uci: str, to_uci: str) -> tuple[bool, str]:
        """Manual/debug move: physical first, then logical (legacy path)."""
        if not self._is_robot_turn(self.latest_white_to_move):
            return False, 'not robot turn'
        uci = f'{from_uci}{to_uci}'
        fen_before = self.latest_fen
        legal = resolve_legal_uci_full(uci, fen_before)
        if legal is None:
            return False, f'illegal move: {uci}'

        sync_ok, sync_msg = self._sync_robot_board(fen_before)
        if not sync_ok:
            return False, sync_msg

        physical_ok, physical_msg = self._execute_physical_move(legal, fen=fen_before)
        if not physical_ok:
            return False, physical_msg

        if self._vision_mode():
            logical_ok, logical_msg, _ = self._apply_robot_move_service(
                legal,
                fen_before,
            )
            if not logical_ok:
                return False, logical_msg

        self.latest_from = legal[:2]
        self.latest_to = legal[2:4]
        return True, physical_msg

    def execute_voice_command(self, transcript: str) -> dict[str, Any]:
        transcript = (transcript or '').strip()
        base: dict[str, Any] = {
            'success': False,
            'message': '',
            'from': '',
            'to': '',
            'transcript': transcript,
            'parse_error': False,
            'promotion_required': False,
            'voice_action': 'parse_error',
        }

        if self.game_phase == 'finished':
            base['message'] = '게임이 종료되었습니다'
            return base

        if self.bot_status in ('thinking', 'moving'):
            raise RuntimeError('봇이 동작 중입니다. 잠시 후 다시 시도하세요.')

        if not transcript:
            self._set_bot_banter(react_to_voice_empty(self._difficulty()))
            base['message'] = self.bot_message
            self.latest_message = base['message']
            self._persist_game_state()
            return base

        game_action = parse_game_voice_command(transcript)
        if game_action is not None:
            return self._execute_voice_game_action(game_action, transcript, base)

        return self._execute_voice_move_action(transcript, base)

    def execute_voice_player_move(self, transcript: str) -> dict[str, Any]:
        return self.execute_voice_command(transcript)

    def _execute_voice_game_action(
        self,
        action: str,
        transcript: str,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        self.get_logger().info(
            f'voice game command action={action} transcript={transcript!r}'
        )
        base['voice_action'] = action
        success = False
        message = ''
        from_sq = ''
        to_sq = ''

        if action == 'confirm':
            if self._is_robot_turn(self.latest_white_to_move):
                message = '지금은 당신 차례가 아닙니다'
                self._set_bot_banter(react_to_voice_confirm_fail(self._difficulty(), message=message))
            else:
                success, message, from_sq, to_sq = self.confirm_player_move()
                if success:
                    self._set_bot_banter(react_to_voice_confirm_success(self._difficulty()))
                else:
                    self._set_bot_banter(react_to_voice_confirm_fail(self._difficulty(), message=message))
        elif action == 'undo':
            try:
                success, message = self.undo_last_turn()
            except RuntimeError:
                raise
            if success:
                self._set_bot_banter(react_to_voice_undo_success(self._difficulty()))
            else:
                self._set_bot_banter(react_to_voice_undo_fail(self._difficulty(), message=message))
        elif action == 'restore':
            success, message = self.restore_board_physical()
            if success:
                self._set_bot_banter(react_to_voice_restore_success(self._difficulty()))
            else:
                self._set_bot_banter(react_to_voice_restore_fail(self._difficulty(), message=message))
        elif action == 'resign':
            success, message = self.resign_game()
            if success:
                self._set_bot_banter(react_to_voice_resign_success(self._difficulty()))
            else:
                self._set_bot_banter(react_to_voice_resign_fail(self._difficulty(), message=message))

        base['success'] = success
        base['message'] = self.bot_message or message
        base['from'] = from_sq
        base['to'] = to_sq
        self.latest_message = base['message']
        if self._pending_illegal_move:
            base['illegal_move'] = True
        self._spin_for_updates()
        self._persist_game_state()
        return base

    def _execute_voice_move_action(
        self,
        transcript: str,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        base['voice_action'] = 'move'

        if self._is_robot_turn(self.latest_white_to_move):
            base['message'] = '지금은 당신 차례가 아닙니다'
            self.latest_message = base['message']
            return base

        fen_before = self.latest_fen
        parsed, parse_method = parse_voice_command_with_meta(
            transcript,
            fen=fen_before,
            human_color=self._human_color(),
            llm_enabled=self._voice_llm_enabled(),
            llm_auto=self._voice_llm_auto(),
            llm_model=self._voice_llm_model(),
            llm_base_url=self._voice_llm_base_url(),
        )
        if isinstance(parsed, VoiceMoveParseError):
            if parsed.kind == 'ambiguous':
                self._set_bot_banter(react_to_voice_ambiguous(self._difficulty()))
            else:
                self._set_bot_banter(react_to_voice_parse_error(self._difficulty()))
            base['parse_error'] = True
            base['message'] = self.bot_message
            self.latest_message = base['message']
            self._persist_game_state()
            return base

        move = parsed.move
        from_sq = move.from_sq
        to_sq = move.to_sq
        base['from'] = from_sq
        base['to'] = to_sq

        intent_ok, intent_msg = validate_voice_move_intent(
            transcript,
            fen_before,
            self._human_color(),
            move,
        )
        if not intent_ok:
            self._set_bot_banter(react_to_voice_illegal(self._difficulty(), from_sq=from_sq, to_sq=to_sq))
            base['message'] = self.bot_message or intent_msg
            self.latest_message = base['message']
            self._persist_game_state()
            return base

        legal, promo_required, resolve_msg = resolve_voice_move(fen_before, move)

        if promo_required:
            self._pending_promotion = {
                'from': from_sq,
                'to': to_sq,
                'fen_before': fen_before,
            }
            self._set_bot_banter(react_to_voice_promotion_required(self._difficulty()))
            base['promotion_required'] = True
            base['message'] = self.bot_message
            self.latest_message = base['message']
            self.latest_from = from_sq
            self.latest_to = to_sq
            self._persist_game_state()
            return base

        if legal is None:
            self._set_bot_banter(
                react_to_voice_illegal(self._difficulty(), from_sq=from_sq, to_sq=to_sq)
            )
            base['message'] = self.bot_message or resolve_msg
            self.latest_message = base['message']
            self._persist_game_state()
            return base

        self.get_logger().info(
            f'voice move transcript={transcript!r} parse_method={parse_method} uci={legal}'
        )
        base['parsed_summary'] = f'{from_sq}{"x" if chess.Board(fen_before).is_capture(chess.Move.from_uci(legal)) else ""}{to_sq}'

        self._pending_promotion = None
        self._pending_illegal_move = None
        self._ensure_active_game()

        try:
            self._push_undo_snapshot(fen_before, legal, by_robot=False)
            self._record_capture(fen_before, legal, by_robot=False)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'voice move capture/snapshot failed: {exc}')

        sync_ok, sync_msg = self._sync_robot_board(fen_before)
        if not sync_ok:
            base['message'] = sync_msg
            self.latest_message = sync_msg
            return base

        self.bot_status = 'moving'
        self.latest_message = f'음성 명령 이동 중: {from_sq} → {to_sq}'
        physical_ok, physical_msg = self._execute_physical_move(legal, fen=fen_before, for_voice=True)
        if not physical_ok:
            self.bot_status = 'error'
            base['message'] = physical_msg
            self.latest_message = f'로봇 이동 실패: {physical_msg}'
            self._persist_game_state()
            return base

        board = chess.Board(fen_before)
        board.push_uci(legal)
        fen_after = board.fen()

        logical_ok, logical_msg = self._sync_logical_board(fen_after)
        if not logical_ok:
            self.get_logger().warn(f'vision sync after voice move failed: {logical_msg}')
            if not self._push_local_fen_move(legal, fen=fen_before):
                self.bot_status = 'error'
                base['message'] = '보드 상태 반영 실패'
                self.latest_message = base['message']
                self._persist_game_state()
                return base

        self.latest_from = legal[:2]
        self.latest_to = legal[2:4]
        self.bot_status = 'idle'

        try:
            self._process_player_move_feedback(fen_before, legal)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'voice move feedback failed: {exc}')

        promo = legal[4:5] if len(legal) > 4 else ''
        if promo:
            self.promotion_notice = promotion_notice(legal[:2], legal[2:4], promo)

        sync_ok, sync_msg = self._sync_robot_board(fen_after)
        if not sync_ok:
            self.get_logger().warn(f'robot sync after voice move failed: {sync_msg}')

        self._set_bot_banter(
            react_to_voice_success(self._difficulty(), from_sq=from_sq, to_sq=to_sq)
        )
        self._update_game_over_state(fen_after)
        self.is_check = chess.Board(fen_after).is_check()
        if self.game_phase != 'finished':
            self._maybe_play_bot_move(fen_after)

        base['success'] = True
        base['message'] = self.bot_message
        self.latest_message = base['message']
        self._spin_for_updates()
        self._persist_game_state()
        return base


def create_app(node: WebBridgeNode) -> FastAPI:
    app = FastAPI(title='Chess Web Bridge')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.get('/api/board')
    def get_board() -> dict[str, Any]:
        return node.get_board_payload()

    @app.get('/api/games')
    def list_games() -> dict[str, Any]:
        return {'games': node.list_saved_games()}

    @app.post('/api/games/save')
    def save_game() -> dict[str, Any]:
        success, message = node.save_current_game()
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.post('/api/games/load')
    def load_game(req: LoadGameRequest) -> dict[str, Any]:
        success, message = node.load_saved_game(req.game_id)
        if not success:
            raise HTTPException(status_code=404, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.post('/api/games/resume')
    def resume_game() -> dict[str, Any]:
        success, message = node.resume_active_saved_game()
        if not success:
            raise HTTPException(status_code=404, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.post('/api/game/config')
    def set_game_config(req: GameConfigRequest) -> dict[str, Any]:
        try:
            node.set_game_config(
                req.human_color,
                req.difficulty,
                req.board_orientation,
                hand_auto_confirm_enabled=req.hand_auto_confirm_enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'success': True, **node.get_board_payload()}

    @app.post('/api/reset')
    def reset_board() -> dict[str, Any]:
        success, message = node.reset_board()
        if not success:
            raise HTTPException(status_code=503, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.post('/api/restore_board')
    def restore_board() -> dict[str, Any]:
        success, message = node.restore_board_physical()
        if not success:
            raise HTTPException(status_code=503, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.post('/api/resign')
    def resign() -> dict[str, Any]:
        success, message = node.resign_game()
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.post('/api/undo')
    def undo() -> dict[str, Any]:
        try:
            success, message = node.undo_last_turn()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.post('/api/player-moved')
    def player_moved() -> dict[str, Any]:
        success, message, from_sq, to_sq = node.confirm_player_move()
        payload = {
            'success': success,
            'message': message,
            'from': from_sq,
            'to': to_sq,
            **node.get_board_payload(),
        }
        if node._pending_illegal_move:
            payload['illegal_move'] = True
        return payload

    @app.post('/api/twin/verify')
    def twin_verify(req: TwinVerifyRequest) -> dict[str, Any]:
        try:
            payload = node.verify_board_twin(
                confirm_failed=req.confirm_failed,
                use_fresh_scan=req.use_fresh_scan,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {**payload, **node.get_board_payload()}

    @app.get('/api/twin/calibration')
    def twin_calibration_get() -> dict[str, Any]:
        if not node._twin_enabled():
            raise HTTPException(status_code=400, detail='sideview twin is not available in this launch')
        return node.get_side_calibration_payload()

    @app.post('/api/twin/calibration')
    def twin_calibration_save(req: TwinCalibrationRequest) -> dict[str, Any]:
        if not node._twin_enabled():
            raise HTTPException(status_code=400, detail='sideview twin is not available in this launch')
        success, message = node.save_side_calibration(
            req.board_corners,
            flip_files=req.flip_files,
            board_flipped=req.board_flipped,
        )
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {
            'success': True,
            'message': message,
            **node.get_side_calibration_payload(),
            **node.get_twin_live_payload(),
        }

    @app.post('/api/hand/config')
    def hand_config(req: HandConfigRequest) -> dict[str, Any]:
        if not node._hand_enabled():
            raise HTTPException(status_code=400, detail='hand detection is not available in this launch')
        if req.auto_confirm_enabled is not None:
            node.set_hand_auto_confirm_enabled(req.auto_confirm_enabled)
        if req.safety_enabled is not None:
            node.set_hand_safety_enabled(req.safety_enabled)
        return {
            'success': True,
            'hand_auto_confirm_enabled': node.is_hand_auto_confirm_enabled(),
            'hand_safety_enabled': node.is_hand_safety_enabled(),
            **node.get_board_payload(),
            **node.get_twin_live_payload(),
        }

    @app.post('/api/twin/config')
    def twin_config(req: TwinConfigRequest) -> dict[str, Any]:
        if not node._twin_enabled():
            raise HTTPException(status_code=400, detail='sideview twin is not available in this launch')
        node.set_twin_runtime_enabled(req.enabled)
        return {
            'success': True,
            'twin_runtime_enabled': node.is_twin_runtime_enabled(),
            **node.get_twin_live_payload(),
            **node.get_board_payload(),
        }

    @app.post('/api/robot/stop')
    def robot_stop() -> dict[str, Any]:
        ok, message = node.stop_robot_motion()
        if not ok:
            raise HTTPException(status_code=503, detail=message)
        return {'success': ok, 'message': message, **node.get_board_payload()}

    @app.post('/api/robot/stop/resume')
    def robot_stop_resume() -> dict[str, Any]:
        ok, message = node.resume_robot_motion()
        if not ok:
            raise HTTPException(status_code=503, detail=message)
        return {'success': ok, 'message': message, **node.get_board_payload()}

    @app.post('/api/robot/stop/abort')
    def robot_stop_abort() -> dict[str, Any]:
        ok, message = node.abort_robot_motion()
        if not ok:
            raise HTTPException(status_code=503, detail=message)
        return {'success': ok, 'message': message, **node.get_board_payload()}

    @app.post('/api/voice-move')
    def voice_move(req: VoiceMoveRequest) -> dict[str, Any]:
        try:
            result = node.execute_voice_command(req.transcript)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {**result, **node.get_board_payload()}

    @app.post('/api/move')
    def post_move(req: MoveRequest) -> dict[str, Any]:
        from_sq = req.from_square.strip().lower()
        to_sq = req.to.strip().lower()
        if len(from_sq) != 2 or len(to_sq) != 2:
            raise HTTPException(status_code=400, detail='squares must be like e2')
        success, message = node.execute_move(from_sq, to_sq)
        if not success:
            status = 409 if 'not robot turn' in message else 400
            raise HTTPException(status_code=status, detail=message)
        return {
            'success': success,
            'message': message,
            'from': from_sq,
            'to': to_sq,
            **node.get_board_payload(),
        }

    @app.post('/api/player-moved/promote')
    def player_promotion(req: PromotionRequest) -> dict[str, Any]:
        success, message, from_sq, to_sq = node.confirm_player_promotion(req.piece)
        payload = {
            'success': success,
            'message': message,
            'from': from_sq,
            'to': to_sq,
            **node.get_board_payload(),
        }
        return payload

    @app.post('/api/board/correct')
    def correct_board(req: BoardCorrectRequest) -> dict[str, Any]:
        try:
            success, message = node.correct_board(
                req.fen,
                graveyard_slots=req.graveyard_slots,
                human_graveyard_slots=req.human_graveyard_slots,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.post('/api/revert-illegal-move')
    def revert_illegal_move(req: RevertIllegalMoveRequest) -> dict[str, Any]:
        try:
            success, message = node.revert_illegal_move(req.from_square, req.to)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {'success': success, 'message': message, **node.get_board_payload()}

    @app.get('/api/camera/preview.jpg')
    def camera_preview() -> Response:
        jpeg = node.get_preview_jpeg()
        if jpeg is None:
            raise HTTPException(status_code=503, detail='camera preview not available yet')
        return Response(content=jpeg, media_type='image/jpeg')

    @app.get('/api/twin/webcam/preview.jpg')
    def twin_webcam_preview() -> Response:
        jpeg = node.get_sideview_jpeg()
        if jpeg is None:
            raise HTTPException(status_code=503, detail='side webcam preview not available yet')
        return Response(content=jpeg, media_type='image/jpeg')

    @app.get('/api/hand/preview.jpg')
    def hand_preview() -> Response:
        if not node._hand_enabled():
            raise HTTPException(status_code=404, detail='hand detection is not enabled')
        jpeg = node.get_hand_preview_jpeg()
        if jpeg is None:
            raise HTTPException(status_code=503, detail='hand preview not available yet')
        return Response(content=jpeg, media_type='image/jpeg')

    @app.get('/api/twin/live')
    def twin_live() -> dict[str, Any]:
        return node.get_twin_live_payload()

    @app.get('/api/camera/stream')
    async def camera_stream() -> StreamingResponse:
        async def generate():
            boundary = b'--frame'
            while True:
                jpeg = node.get_preview_jpeg()
                if jpeg is not None:
                    yield boundary + b'\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
                await asyncio.sleep(0.15)

        return StreamingResponse(
            generate(),
            media_type='multipart/x-mixed-replace; boundary=frame',
        )

    return app


def run_http_server(node: WebBridgeNode, app: FastAPI) -> None:
    host = node.get_parameter('http_host').value
    preferred = int(node.get_parameter('http_port').value)
    last_error: OSError | None = None

    for port in range(preferred, preferred + 10):
        try:
            node.get_logger().info(f'HTTP bridge: http://{host}:{port}')
            uvicorn.run(app, host=host, port=port, log_level='info')
            return
        except OSError as exc:
            last_error = exc
            if exc.errno == 98 or 'address already in use' in str(exc).lower():
                node.get_logger().warn(
                    f'Port {port} is busy. Stop old bridge: fuser -k {port}/tcp'
                )
                continue
            raise

    raise RuntimeError(
        f'No free HTTP port in {preferred}-{preferred + 9}. '
        f'Last error: {last_error}'
    )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WebBridgeNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    node.attach_executor(executor)
    spin_stop = threading.Event()

    def _spin_executor() -> None:
        while rclpy.ok() and not spin_stop.is_set():
            try:
                executor.spin_once(timeout_sec=0.1)
            except Exception:  # noqa: BLE001
                break

    spin_thread = threading.Thread(target=_spin_executor, daemon=True, name='ros_executor_spin')
    spin_thread.start()
    for _ in range(30):
        time.sleep(0.05)

    app = create_app(node)
    try:
        run_http_server(node, app)
    except KeyboardInterrupt:
        pass
    finally:
        spin_stop.set()
        spin_thread.join(timeout=2.0)
        node.shutdown()
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
