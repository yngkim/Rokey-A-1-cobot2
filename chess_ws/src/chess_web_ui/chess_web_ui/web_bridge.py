#!/usr/bin/env python3
"""HTTP bridge between React UI and ROS2 pick-place node."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Literal

import chess
import cv2
import rclpy
import uvicorn
from chess_game.board_utils import occupancy_from_fen
from chess_engine.stockfish_client import StockfishClient
from chess_web_ui.bot_banter import (
    Difficulty,
    get_bot_profile,
    greeting,
    react_to_bot_move,
    react_to_player_move,
)
from chess_msgs.action import ExecuteMove
from chess_msgs.msg import BoardState, ChessMove, GameSnapshot
from chess_msgs.srv import ApplyRobotMove, ConfirmPlayerMove, ResetBoard, ScanInitial
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

        self.latest_fen = (
            'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
        )
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
        self.game_phase: Literal['lobby', 'playing', 'finished'] = 'lobby'
        self._ply_counter = 0

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
        self.action_client = ActionClient(self, ExecuteMove, 'robot/execute_move')
        self.get_logger().info(
            f'Web bridge ready (human={self._human_color()}, auto_bot={self._auto_bot_move()})'
        )

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

    def _difficulty(self) -> Difficulty:
        level = str(self.get_parameter('difficulty').value).strip().lower()
        if level in {'easy', 'medium', 'hard'}:
            return level  # type: ignore[return-value]
        return 'medium'

    def _bot_profile_payload(self) -> dict[str, str]:
        return get_bot_profile(self._difficulty())

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
        try:
            board = chess.Board(fen)
            move = chess.Move.from_uci(uci)
            return move in board.legal_moves
        except (ValueError, AssertionError):
            return False

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
        if not fen or not self._auto_bot_move():
            return
        parts = fen.split()
        white_to_move = len(parts) > 1 and parts[1] == 'w'
        if not self._is_robot_turn(white_to_move):
            return
        with self._bot_lock:
            if self._bot_busy:
                return
            if fen == self._bot_pending_fen:
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
            success, message = self.execute_bot_move(from_sq, to_sq, fen=fen)
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

    def _record_capture(
        self,
        fen_before: str,
        from_uci: str,
        to_uci: str,
        *,
        by_robot: bool,
    ) -> None:
        try:
            board = chess.Board(fen_before)
            move = chess.Move.from_uci(f'{from_uci}{to_uci}')
            if not board.is_capture(move):
                return
            captured = board.piece_at(move.to_square)
            if captured is None:
                return
            human_is_white = self._human_color() == 'white'
            piece_is_white = captured.color == chess.WHITE
            capturer_is_white = not human_is_white if by_robot else human_is_white
            if piece_is_white == capturer_is_white:
                return
            symbol = captured.symbol()
            if by_robot:
                self.robot_captures.append(symbol)
            else:
                self.human_captures.append(symbol)
        except ValueError:
            pass

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
            'bot_profile': self._bot_profile_payload(),
            'game_phase': self.game_phase,
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
        self.last_bot_move = ''
        self.bot_status = 'idle'
        self.human_captures = []
        self.robot_captures = []
        self.move_history = []
        self._ply_counter = 0
        self.eval_cp = self._eval_from_human_perspective(
            'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
        )
        self.bot_message = greeting(self._difficulty())
        self.game_phase = 'playing'

        success, message = self._reset_robot()
        if not success:
            return False, message
        if not self._vision_mode():
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
        self._maybe_play_bot_move(self.latest_fen)
        return bool(result.success), result.message

    def _reset_robot(self) -> tuple[bool, str]:
        if not self.reset_client.wait_for_service(timeout_sec=2.0):
            return False, 'reset service unavailable'
        future = self.reset_client.call_async(ResetBoard.Request())
        rclpy.spin_until_future_complete(self, future, timeout_sec=30.0)
        if not future.done() or future.result() is None:
            return False, 'reset call failed'
        result = future.result()
        return bool(result.success), result.message

    def confirm_player_move(self) -> tuple[bool, str, str, str]:
        result, err = self._call_service(
            self.confirm_player_client,
            ConfirmPlayerMove.Request(),
            timeout_sec=90.0,
        )
        if result is None:
            return False, err, '', ''
        fen_before = self.latest_fen
        self.latest_from = result.from_square
        self.latest_to = result.to_square
        if result.board_state is not None:
            self._apply_board_state_msg(result.board_state)
        if result.success and result.from_square and result.to_square:
            uci = f'{result.from_square}{result.to_square}'
            if self._is_legal_uci(fen_before, uci):
                self._record_capture(
                    fen_before,
                    result.from_square,
                    result.to_square,
                    by_robot=False,
                )
                self._process_player_move_feedback(
                    fen_before,
                    result.from_square,
                    result.to_square,
                )
            else:
                self.get_logger().warn(
                    f'vision move not legal on board: {uci} (fen={fen_before})'
                )
        if getattr(result, 'fen', ''):
            self._sync_from_fen(result.fen)
        elif result.success:
            self.eval_cp = self._eval_from_human_perspective()
        self._spin_for_updates()
        if result.success:
            self._maybe_play_bot_move(self.latest_fen)
        return (
            bool(result.success),
            result.message,
            result.from_square,
            result.to_square,
        )

    def _process_player_move_feedback(
        self,
        fen_before: str,
        from_sq: str,
        to_sq: str,
    ) -> None:
        uci = f'{from_sq}{to_sq}'
        if not self._is_legal_uci(fen_before, uci):
            return

        board = chess.Board(fen_before)
        move = chess.Move.from_uci(uci)
        is_capture = board.is_capture(move)
        board.push(move)
        is_check = board.is_check()

        classification = self._with_engine(
            lambda: self._engine.classify_move(fen_before, uci)
        )
        self.eval_cp = self._eval_from_human_perspective()
        self._append_move_history(
            fen_before=fen_before,
            uci=uci,
            color=self._human_color(),
            eval_cp=self.eval_cp,
            quality=classification.quality,
        )
        san = self._uci_to_san(fen_before, uci)
        self.bot_message = react_to_player_move(
            self._difficulty(),
            quality=classification.quality,
            is_capture=is_capture,
            is_check=is_check,
            san=san,
        )

    def _process_bot_move_feedback(self, fen_before: str, from_uci: str, to_uci: str) -> None:
        uci = f'{from_uci}{to_uci}'
        if not self._is_legal_uci(fen_before, uci):
            return

        board = chess.Board(fen_before)
        move = chess.Move.from_uci(uci)
        is_capture = board.is_capture(move)
        board.push(move)
        is_check = board.is_check()

        self.eval_cp = self._eval_from_human_perspective()
        self._append_move_history(
            fen_before=fen_before,
            uci=uci,
            color=self._robot_color(),
            eval_cp=self.eval_cp,
        )
        self.bot_message = react_to_bot_move(
            self._difficulty(),
            is_capture=is_capture,
            is_check=is_check,
        )

    def _apply_robot_move_service(
        self,
        from_uci: str,
        to_uci: str,
        *,
        is_capture: bool,
        timeout_sec: float = 30.0,
    ) -> tuple[bool, str, object | None]:
        from_col = ord(from_uci[0]) - ord('a')
        from_row = int(from_uci[1]) - 1
        to_col = ord(to_uci[0]) - ord('a')
        to_row = int(to_uci[1]) - 1

        apply_req = ApplyRobotMove.Request()
        apply_req.move = ChessMove()
        apply_req.move.from_square.col = from_col
        apply_req.move.from_square.row = from_row
        apply_req.move.to_square.col = to_col
        apply_req.move.to_square.row = to_row
        apply_req.move.promotion = ''
        apply_req.move.is_capture = is_capture
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
        return True, apply_result.message, apply_result

    def _execute_physical_move(self, from_uci: str, to_uci: str, *, is_capture: bool) -> tuple[bool, str]:
        if not self.action_client.wait_for_server(timeout_sec=5.0):
            return False, 'execute_move action unavailable'

        from_col = ord(from_uci[0]) - ord('a')
        from_row = int(from_uci[1]) - 1
        to_col = ord(to_uci[0]) - ord('a')
        to_row = int(to_uci[1]) - 1

        goal = ExecuteMove.Goal()
        goal.move.from_square.col = from_col
        goal.move.from_square.row = from_row
        goal.move.to_square.col = to_col
        goal.move.to_square.row = to_row
        goal.move.promotion = ''
        goal.move.is_capture = is_capture

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

    def _push_local_fen_move(self, from_uci: str, to_uci: str, *, fen: str) -> bool:
        """Apply a move to local FEN only (fallback when vision_game sync fails)."""
        try:
            board = chess.Board(fen)
            move = chess.Move.from_uci(f'{from_uci}{to_uci}')
            if move not in board.legal_moves:
                return False
            board.push(move)
            self._sync_from_fen(board.fen())
            return True
        except ValueError:
            return False

    def _mark_bot_move_metadata(self, from_uci: str, to_uci: str) -> None:
        self.latest_from = from_uci
        self.latest_to = to_uci
        self.last_bot_move = f'{from_uci}{to_uci}'

    def execute_bot_move(
        self,
        from_uci: str,
        to_uci: str,
        *,
        fen: str | None = None,
    ) -> tuple[bool, str]:
        """Move the arm first; update grid and vision_game only after physical success."""
        fen_before = fen or self.latest_fen
        is_capture = self._move_is_capture(from_uci, to_uci, fen=fen_before)

        physical_ok, physical_msg = self._execute_physical_move(
            from_uci,
            to_uci,
            is_capture=is_capture,
        )
        if not physical_ok:
            self.latest_message = f'로봇 이동 실패: {physical_msg}'
            return False, physical_msg

        logical_synced = False
        if self._vision_mode():
            logical_ok, logical_msg, _ = self._apply_robot_move_service(
                from_uci,
                to_uci,
                is_capture=is_capture,
                timeout_sec=10.0,
            )
            if logical_ok:
                logical_synced = True
            else:
                self.get_logger().warn(
                    f'vision_game sync failed after arm moved: {logical_msg}; applying local FEN'
                )

        if not logical_synced and not self._push_local_fen_move(
            from_uci, to_uci, fen=fen_before
        ):
            self.latest_message = (
                f'로봇은 이동했으나 보드 상태 반영 실패: {from_uci} → {to_uci}'
            )
            return False, 'logical board update failed after physical move'

        self._record_capture(fen_before, from_uci, to_uci, by_robot=True)
        self._mark_bot_move_metadata(from_uci, to_uci)
        self._process_bot_move_feedback(fen_before, from_uci, to_uci)
        self.latest_message = f'로봇 수: {from_uci} → {to_uci}'
        return True, physical_msg

    def _move_is_capture(self, from_uci: str, to_uci: str, *, fen: str | None = None) -> bool:
        try:
            board = chess.Board(fen or self.latest_fen)
            move = chess.Move.from_uci(f'{from_uci}{to_uci}')
            return board.is_capture(move)
        except ValueError:
            return False

    def execute_move(self, from_uci: str, to_uci: str) -> tuple[bool, str]:
        """Manual/debug move: physical first, then logical (legacy path)."""
        is_capture = self._move_is_capture(from_uci, to_uci)
        physical_ok, physical_msg = self._execute_physical_move(
            from_uci,
            to_uci,
            is_capture=is_capture,
        )
        if not physical_ok:
            return False, physical_msg

        if self._vision_mode():
            logical_ok, logical_msg, _ = self._apply_robot_move_service(
                from_uci,
                to_uci,
                is_capture=is_capture,
            )
            if not logical_ok:
                return False, logical_msg

        self.latest_from = from_uci
        self.latest_to = to_uci
        return True, physical_msg


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
        return payload

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
