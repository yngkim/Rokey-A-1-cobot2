"""Turn guard and hand-pause release behavior."""

from __future__ import annotations

import threading
import types

from chess_web_ui.web_bridge import WebBridgeNode


def _minimal_node(**overrides) -> WebBridgeNode:
    node = WebBridgeNode.__new__(WebBridgeNode)
    node._bot_lock = threading.Lock()
    node._hand_lock = threading.Lock()
    node._bot_session_active = True
    node.game_phase = 'playing'
    node.latest_fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    node.latest_white_to_move = True
    node.bot_status = 'paused'
    node._hand_safety_paused = True
    node._hand_in_board = False
    node._hand_raw_in_board = False
    node._hand_safety_runtime = True
    node._bot_busy = False
    node._bot_worker_thread = None
    node._restore_in_progress = False
    node._active_move_goal_handle = None
    node._bot_status_before_pause = 'thinking'
    node._hand_last_published_in_board = True
    node._pending_vision_auto_move = None
    node._vision_auto_move_in_progress = False
    node._auto_move_lock = threading.Lock()
    node._last_auto_move_uci = ''
    node._last_auto_move_at = 0.0
    node._last_bot_resume_attempt_at = 0.0
    node._active_game_id = 'test'
    node._board_reset_in_progress = False
    node._bot_cancel_requested = False
    node._bot_pending_fen = ''
    node._bot_activity_started_at = 0.0
    node.get_logger = lambda: types.SimpleNamespace(info=lambda *a, **k: None, warn=lambda *a, **k: None)
    node._publish_hand_in_board = lambda *a, **k: None
    node._ensure_hand_clear_for_robot = lambda: None
    node._try_process_pending_vision_auto_move = lambda: None
    node._maybe_resume_bot_after_player_move = lambda: None
    node.get_parameter = lambda name: types.SimpleNamespace(
        value=overrides.get(name, True if name == 'hand_safety_enabled' else False)
    )
    node._is_human_turn = WebBridgeNode._is_human_turn.__get__(node, WebBridgeNode)
    node._is_robot_turn = WebBridgeNode._is_robot_turn.__get__(node, WebBridgeNode)
    node._human_color = lambda: overrides.get('human_color', 'white')
    node._hand_blocks_robot = WebBridgeNode._hand_blocks_robot.__get__(node, WebBridgeNode)
    node._bot_motion_active = WebBridgeNode._bot_motion_active.__get__(node, WebBridgeNode)
    node._release_hand_safety_pause = WebBridgeNode._release_hand_safety_pause.__get__(
        node, WebBridgeNode
    )
    return node


def test_release_hand_safety_pause_clears_stale_thinking_status():
    node = _minimal_node()
    node._release_hand_safety_pause()
    assert node._hand_safety_paused is False
    assert node.bot_status == 'idle'


def test_bot_fen_trustworthy_rejects_start_with_history():
    node = _minimal_node(human_color='black')
    node.move_history = [{'ply': 1}, {'ply': 2}, {'ply': 3}, {'ply': 4}]
    node._ply_counter = 4
    node.latest_fen = 'rnbqkbnr/pppp2pp/5p2/4N3/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 3'
    node._bot_fen_trustworthy = WebBridgeNode._bot_fen_trustworthy.__get__(
        node, WebBridgeNode
    )
    assert node._bot_fen_trustworthy('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1') is False
    assert node._bot_fen_trustworthy(node.latest_fen) is True


def test_release_hand_pause_idle_when_human_turn_after_arm_done():
    node = _minimal_node(human_color='black')
    node.latest_white_to_move = False
    node._hand_safety_paused = True
    node.bot_status = 'paused'
    node._bot_status_before_pause = 'moving'
    node._bot_busy = True
    node._bot_worker_thread = threading.current_thread()
    node._resolve_bot_status_after_hand_release = (
        WebBridgeNode._resolve_bot_status_after_hand_release.__get__(node, WebBridgeNode)
    )
    node._release_hand_safety_pause = WebBridgeNode._release_hand_safety_pause.__get__(
        node, WebBridgeNode
    )
    node._release_hand_safety_pause()
    assert node.bot_status == 'idle'
    assert node._hand_safety_paused is False


def test_enforce_skips_while_execute_move_goal_active():
    node = _minimal_node(human_color='black')
    node.latest_fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
    node.latest_white_to_move = False
    node._enforce_human_turn_arm_safety = WebBridgeNode._enforce_human_turn_arm_safety.__get__(
        node, WebBridgeNode
    )
    node.bot_status = 'moving'
    node._bot_busy = True
    node._active_move_goal_handle = object()
    stopped = node._enforce_human_turn_arm_safety()
    assert stopped is False
    assert node.bot_status == 'moving'


def test_human_turn_enforce_clears_paused_bot_state():
    node = _minimal_node(human_color='white')
    node._cancel_active_robot_goals = lambda: None
    node._call_trigger_service = lambda *a, **k: (True, 'ok')
    node.robot_user_stop_client = object()
    node._publish_hand_in_board = lambda *a, **k: None
    node._enforce_human_turn_arm_safety = WebBridgeNode._enforce_human_turn_arm_safety.__get__(
        node, WebBridgeNode
    )
    node.bot_status = 'moving'
    node._bot_busy = True
    node._bot_worker_thread = threading.Thread(target=lambda: None)
    node._bot_worker_thread.start()
    node._bot_worker_thread.join(timeout=1.0)
    node._bot_busy = True
    node._bot_worker_thread = threading.current_thread()

    stopped = node._enforce_human_turn_arm_safety()
    assert stopped is False
    assert node.bot_status == 'idle'


def test_recover_stale_does_not_clear_active_worker():
    node = _minimal_node(human_color='black')
    node._cancel_active_robot_goals = lambda: None
    node._ensure_hand_clear_for_robot = lambda: None
    node._active_move_goal_handle = None
    node._bot_busy = True
    node.bot_status = 'moving'
    node._bot_worker_thread = threading.current_thread()
    node._recover_stale_bot_activity = WebBridgeNode._recover_stale_bot_activity.__get__(
        node, WebBridgeNode
    )
    assert node._recover_stale_bot_activity() is False
    assert node._bot_busy is True
    assert node.bot_status == 'moving'


def test_maybe_play_bot_move_trust_fen_bypasses_history_gate():
    node = _minimal_node(human_color='black')
    node._bot_session_active = True
    node.game_phase = 'playing'
    node.latest_white_to_move = True
    node._is_human_turn = lambda _wtm: False
    node._is_robot_turn = lambda _wtm: True
    node._hand_blocks_robot = lambda: False
    node._recover_stale_bot_activity = lambda: False
    node._auto_bot_move = lambda: False
    trustworthy_calls: list[str] = []
    node._bot_fen_trustworthy = lambda fen: trustworthy_calls.append(fen) or False
    node._maybe_play_bot_move = WebBridgeNode._maybe_play_bot_move.__get__(
        node, WebBridgeNode
    )
    fen = 'rnbqkb1r/1p3ppp/p2ppn2/2pP4/2B1P3/2N5/PPP2PPP/R1BQK1NR w KQkq - 0 6'
    node._maybe_play_bot_move(fen, trust_fen=False)
    assert len(trustworthy_calls) == 1
    trustworthy_calls.clear()
    node._maybe_play_bot_move(fen, trust_fen=True)
    assert len(trustworthy_calls) == 0
