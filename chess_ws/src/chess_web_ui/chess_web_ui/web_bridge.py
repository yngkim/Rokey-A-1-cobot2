#!/usr/bin/env python3
"""HTTP bridge between React UI and ROS2 pick-place node."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Literal

import chess
import cv2
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
from chess_web_ui.bot_banter import (
    Difficulty,
    get_bot_profile,
    greeting,
    react_to_bot_move,
    react_to_game_over,
    react_to_illegal_move,
    react_to_illegal_move_reverted,
    react_to_player_move,
    react_to_voice_empty,
    react_to_voice_illegal,
    react_to_voice_parse_error,
    react_to_voice_promotion_required,
    react_to_voice_success,
)
from chess_web_ui.board_correct_utils import infer_human_move_uci
from chess_web_ui.capture_utils import resolve_capture_symbol
from chess_web_ui.voice_move_parser import (
    VoiceMoveParseError,
    VoiceMoveParseOk,
    parse_voice_move,
    resolve_voice_move,
)
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
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import Image

BotStatus = Literal['idle', 'thinking', 'moving', 'error']


class MoveRequest(BaseModel):
    from_square: str = Field(alias='from')
    to: str

    model_config = {'populate_by_name': True}


class GameConfigRequest(BaseModel):
    human_color: str
    difficulty: str = 'medium'


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
        self.declare_parameter('engine_depth', 8)
        self.declare_parameter('difficulty', 'medium')
        self.declare_parameter('game_db_path', '~/.chess/games.db')
        self.declare_parameter('restore_saved_game', True)

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
        self._active_game_id = ''
        db_path = str(self.get_parameter('game_db_path').value)
        self._game_store = GameStore(db_path)

        self._preview_lock = threading.Lock()
        self._preview_jpeg: bytes | None = None
        self._preview_annotated_at = 0.0
        self._preview_bridge = CvBridge()

        self._bot_lock = threading.Lock()
        self._bot_busy = False
        self._bot_pending_fen = ''
        self._engine_lock = threading.Lock()
        engine_depth = int(self.get_parameter('engine_depth').value)
        self._engine = StockfishClient(depth=engine_depth)
        self._engine.configure_opponent(self._difficulty())

        self.create_subscription(GameSnapshot, 'chess/game_snapshot', self._on_snapshot, 10)
        self.create_subscription(BoardState, 'chess/board_state', self._on_board, 10)
        self.create_subscription(BoardState, 'vision/live_occupancy', self._on_live_occupancy, 10)
        if bool(self.get_parameter('enable_camera_preview').value):
            topic = str(self.get_parameter('camera_preview_topic').value)
            self.create_subscription(Image, topic, self._on_preview_image, 10)
            fallback = str(self.get_parameter('camera_fallback_topic').value)
            self.create_subscription(Image, fallback, self._on_fallback_camera, 10)
            self.get_logger().info(
                f'Camera preview: {topic} (fallback {fallback})'
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
        self.get_logger().info(
            f'Web bridge ready (human={self._human_color()}, auto_bot={self._auto_bot_move()}, '
            f'db={self._game_store.db_path})'
        )
        if bool(self.get_parameter('restore_saved_game').value):
            self._restore_timer = self.create_timer(4.0, self._try_restore_saved_game)

    def shutdown(self) -> None:
        self._engine.stop()

    def _vision_mode(self) -> bool:
        return bool(self.get_parameter('vision_mode').value)

    def _auto_bot_move(self) -> bool:
        return bool(self.get_parameter('auto_bot_move').value)

    def _human_color(self) -> str:
        color = str(self.get_parameter('human_color').value).strip().lower()
        return color if color in {'white', 'black'} else 'white'

    def _robot_color(self) -> str:
        return 'black' if self._human_color() == 'white' else 'white'

    def _is_robot_turn(self, white_to_move: bool) -> bool:
        robot_is_white = self._human_color() == 'black'
        return white_to_move == robot_is_white

    @staticmethod
    def _is_illegal_move_result(result, *, legal: bool, uci: str) -> bool:
        msg = (getattr(result, 'message', '') or '').lower()
        if 'illegal move' in msg:
            return True
        return bool(getattr(result, 'success', False) and uci and not legal)

    def _difficulty(self) -> Difficulty:
        level = str(self.get_parameter('difficulty').value).strip().lower()
        if level in {'easy', 'medium', 'hard'}:
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

    def _with_engine(self, fn):
        with self._engine_lock:
            return fn()

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
        if hasattr(self, '_restore_timer'):
            self._restore_timer.cancel()
        record = self._game_store.load_active_game()
        if record is None:
            self.get_logger().info('No saved game to restore')
            return
        if record.game_phase == 'lobby':
            return

        self.get_logger().info(
            f'Restoring saved game {record.id[:8]}… fen={record.fen.split()[0]} '
            f'moves={len(record.move_history)}'
        )
        self._apply_game_record(record)
        with self._bot_lock:
            self._bot_busy = False
            self._bot_pending_fen = ''

        logical_ok, logical_msg = self._sync_logical_board(record.fen)
        if not logical_ok:
            self.get_logger().warn(f'vision restore failed: {logical_msg}')
        sync_ok, sync_msg = self._sync_robot_board(record.fen)
        if not sync_ok:
            self.get_logger().warn(f'robot restore failed: {sync_msg}')
        self._refresh_game_phase(record.fen)
        self.latest_message = '저장된 게임을 복원했습니다'
        self._spin_for_updates()
        self._persist_game_state()

    def set_game_config(self, human_color: str, difficulty: str | None = None) -> None:
        color = human_color.strip().lower()
        if color not in {'white', 'black'}:
            raise ValueError('human_color must be white or black')
        with self._bot_lock:
            if self._bot_busy:
                raise RuntimeError('cannot change color while bot is moving')
        params = [Parameter('human_color', Parameter.Type.STRING, color)]
        if difficulty is not None:
            level = difficulty.strip().lower()
            if level not in {'easy', 'medium', 'hard'}:
                raise ValueError('difficulty must be easy, medium, or hard')
            params.append(Parameter('difficulty', Parameter.Type.STRING, level))
            self._engine.configure_opponent(level)  # type: ignore[arg-type]
        self.set_parameters(params)
        self.get_logger().info(
            f'Game config: human={color}, robot={self._robot_color()}, '
            f'difficulty={self._difficulty()}'
        )

    def _on_snapshot(self, msg: GameSnapshot) -> None:
        if msg.fen:
            self.latest_fen = msg.fen
        self.latest_white_to_move = bool(msg.white_to_move)
        self.latest_move_number = int(msg.move_number)

    def _maybe_play_bot_move(self, fen: str) -> None:
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
        with self._bot_lock:
            if self._bot_busy:
                self.get_logger().warn('bot move skipped: bot busy')
                return
            if fen == self._bot_pending_fen:
                self.get_logger().warn('bot move skipped: duplicate pending FEN')
                return
            self._bot_busy = True
            self._bot_pending_fen = fen

        def worker() -> None:
            try:
                self._run_bot_move(fen)
            finally:
                with self._bot_lock:
                    self._bot_busy = False
                    self._bot_pending_fen = ''

        threading.Thread(target=worker, daemon=True).start()

    def _run_bot_move(self, fen: str) -> None:
        try:
            self.bot_status = 'thinking'
            self.latest_message = '로봇이 수를 계산 중...'
            time.sleep(0.5)

            self._engine.configure_opponent(self._difficulty())
            uci = self._with_engine(lambda: self._engine.choose_move(fen))
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
        except Exception as exc:  # noqa: BLE001
            self.bot_status = 'error'
            self.latest_message = f'로봇 수 오류: {exc}'
            self.get_logger().error(f'Bot move error: {exc}')

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
        payload: dict[str, Any] = {
            'fen': self.latest_fen,
            'occupancy': self.latest_occupancy,
            'message': self.latest_message,
            'white_to_move': self.latest_white_to_move,
            'human_color': self._human_color(),
            'robot_color': self._robot_color(),
            'bot_status': self.bot_status,
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
        return payload

    def _call_service(self, client, request, timeout_sec: float = 60.0):
        if not client.wait_for_service(timeout_sec=5.0):
            return None, 'service unavailable'
        future = client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=timeout_sec)
        if not future.done():
            return None, f'service call timed out after {timeout_sec}s'
        if future.result() is None:
            return None, 'service call failed'
        return future.result(), ''

    def _spin_for_updates(self, count: int = 10) -> None:
        for _ in range(count):
            rclpy.spin_once(self, timeout_sec=0.05)

    def reset_board(self) -> tuple[bool, str]:
        with self._bot_lock:
            self._bot_pending_fen = ''
            self._bot_busy = False
        self.last_bot_move = ''
        self.bot_status = 'idle'
        self.human_captures = []
        self.robot_captures = []
        self.move_history = []
        self._ply_counter = 0
        self.graveyard_slots = [None] * 16
        self.human_graveyard_slots = [None] * 16
        self._undo_snapshots = []
        self._pending_promotion = None
        self._pending_illegal_move = None
        self.eval_cp = self._eval_from_human_perspective(START_FEN)
        self._set_bot_banter(greeting(self._difficulty()))
        self.game_phase = 'playing'
        self.game_result = ''
        self.winner = ''
        self.is_check = False
        self.promotion_notice = ''

        success, message = self._reset_robot()
        if not success:
            return False, message
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
            self._maybe_play_bot_move(self.latest_fen)
            return True, message

        result, err = self._call_service(self.scan_initial_client, ScanInitial.Request(), timeout_sec=90.0)
        if result is None:
            return False, err
        self.latest_from = ''
        self.latest_to = ''
        if result.board_state is not None:
            self._apply_board_state_msg(result.board_state)
        if getattr(result, 'fen', ''):
            self._sync_from_fen(result.fen)
        self.eval_cp = self._eval_from_human_perspective()
        self._spin_for_updates()
        if self.latest_fen:
            sync_ok, sync_msg = self._sync_robot_board(self.latest_fen)
            if not sync_ok:
                self.get_logger().warn(f'robot board sync after initial scan failed: {sync_msg}')
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
        self._maybe_play_bot_move(self.latest_fen)
        return bool(result.success), result.message

    def restore_board_physical(self) -> tuple[bool, str]:
        if not self.restore_action_client.wait_for_server(timeout_sec=5.0):
            return False, 'restore_board action unavailable'

        if self.latest_fen.strip():
            sync_ok, sync_msg = self._sync_robot_board(self.latest_fen)
            if not sync_ok:
                return False, sync_msg

        send_future = self.restore_action_client.send_goal_async(RestoreBoard.Goal())
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=10.0)
        if not send_future.done() or send_future.result() is None:
            return False, 'failed to send restore goal'

        goal_handle = send_future.result()
        if not goal_handle.accepted:
            return False, 'restore goal rejected'

        result_future = goal_handle.get_result_async()
        deadline = time.time() + 600.0
        while time.time() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if result_future.done():
                break
        if not result_future.done():
            goal_handle.cancel_goal_async()
            return False, 'restore timed out'

        result = result_future.result().result
        if not result.success:
            return False, result.message

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
        if self.bot_status in ('thinking', 'moving'):
            with self._bot_lock:
                self._bot_pending_fen = ''
                self._bot_busy = False
            self.bot_status = 'idle'
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

    def _reset_robot(self) -> tuple[bool, str]:
        if not self.reset_client.wait_for_service(timeout_sec=2.0):
            return False, 'reset service unavailable'
        future = self.reset_client.call_async(ResetBoard.Request())
        rclpy.spin_until_future_complete(self, future, timeout_sec=30.0)
        if not future.done() or future.result() is None:
            return False, 'reset call failed'
        result = future.result()
        return bool(result.success), result.message

    def _sync_robot_board(self, fen: str) -> tuple[bool, str]:
        """Sync pick_place_node internal FEN/occupancy with the logical game state."""
        fen = (fen or '').strip()
        if not fen:
            return False, 'empty FEN for robot sync'
        request = SetBoard.Request(fen=fen)
        request.graveyard_slots_json = json.dumps(self.graveyard_slots)
        request.human_graveyard_slots_json = json.dumps(self.human_graveyard_slots)
        result, err = self._call_service(
            self.robot_set_board_client,
            request,
            timeout_sec=10.0,
        )
        if result is None:
            return False, f'robot board sync failed: {err}'
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
        success = bool(result.success) and legal
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

        self._spin_for_updates()
        if success and bot_fen:
            sync_ok, sync_msg = self._sync_robot_board(bot_fen)
            if not sync_ok:
                self.get_logger().warn(
                    f'robot board sync after player move failed: {sync_msg}'
                )
            self._update_game_over_state(bot_fen)
            self.is_check = chess.Board(bot_fen).is_check()
            if self.game_phase != 'finished':
                self._maybe_play_bot_move(bot_fen)
            else:
                self.get_logger().info('bot move skipped after player move: game finished')

        if not success and 'no move detected' in (result.message or '').lower():
            if (
                self.game_phase != 'finished'
                and self._is_robot_turn(self.latest_white_to_move)
            ):
                self.get_logger().info(
                    'confirm: board already reflects last move; triggering bot'
                )
                self._maybe_play_bot_move(self.latest_fen)
                self._persist_game_state()
                return (
                    True,
                    '이미 반영된 수입니다. 로봇이 응수합니다.',
                    result.from_square,
                    result.to_square,
                )

        if success or result.success:
            self._persist_game_state()

        message = self.latest_message if not success and not legal else result.message
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
        if human_graveyard_slots is not None:
            self.human_graveyard_slots = list(human_graveyard_slots)
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
            self._maybe_play_bot_move(self.latest_fen)
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

    def _execute_physical_move(self, uci: str, *, fen: str) -> tuple[bool, str]:
        if not self.action_client.wait_for_server(timeout_sec=5.0):
            return False, 'execute_move action unavailable'

        goal = ExecuteMove.Goal()
        goal.move = ChessMove()
        self._fill_chess_move(goal.move, fen, uci)

        send_future = self.action_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=10.0)
        if not send_future.done() or send_future.result() is None:
            return False, 'failed to send goal'

        goal_handle = send_future.result()
        if not goal_handle.accepted:
            return False, 'goal rejected'

        result_future = goal_handle.get_result_async()
        deadline = time.time() + 180.0
        while time.time() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if result_future.done():
                break
        if not result_future.done():
            goal_handle.cancel_goal_async()
            return False, 'move timed out'

        result = result_future.result().result
        if not result.success:
            return False, result.message
        return True, result.message

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

        sync_ok, sync_msg = self._sync_robot_board(fen_before)
        if not sync_ok:
            return False, sync_msg

        physical_ok, physical_msg = self._execute_physical_move(legal, fen=fen_before)
        if not physical_ok:
            self.latest_message = f'로봇 이동 실패: {physical_msg}'
            return False, physical_msg

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

    def execute_voice_player_move(self, transcript: str) -> dict[str, Any]:
        transcript = (transcript or '').strip()
        base: dict[str, Any] = {
            'success': False,
            'message': '',
            'from': '',
            'to': '',
            'transcript': transcript,
            'parse_error': False,
            'promotion_required': False,
        }

        if self.game_phase == 'finished':
            base['message'] = '게임이 종료되었습니다'
            return base

        if self.bot_status in ('thinking', 'moving'):
            raise RuntimeError('봇이 동작 중입니다. 잠시 후 다시 시도하세요.')

        if self._is_robot_turn(self.latest_white_to_move):
            base['message'] = '지금은 당신 차례가 아닙니다'
            self.latest_message = base['message']
            return base

        if not transcript:
            self._set_bot_banter(react_to_voice_empty(self._difficulty()))
            base['message'] = self.bot_message
            self.latest_message = base['message']
            self._persist_game_state()
            return base

        parsed = parse_voice_move(transcript)
        if isinstance(parsed, VoiceMoveParseError):
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

        fen_before = self.latest_fen
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
        physical_ok, physical_msg = self._execute_physical_move(legal, fen=fen_before)
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

    @app.post('/api/game/config')
    def set_game_config(req: GameConfigRequest) -> dict[str, Any]:
        try:
            node.set_game_config(req.human_color, req.difficulty)
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

    @app.post('/api/voice-move')
    def voice_move(req: VoiceMoveRequest) -> dict[str, Any]:
        try:
            result = node.execute_voice_player_move(req.transcript)
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
            raise HTTPException(status_code=400, detail=message)
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
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    app = create_app(node)
    try:
        run_http_server(node, app)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
