"""Tests for bot banter speech kinds."""

from chess_web_ui.bot_banter import (
    greeting,
    react_to_bot_move,
    react_to_game_over,
    react_to_illegal_move,
    react_to_illegal_move_reverted,
    react_to_player_move,
    react_to_voice_illegal,
    react_to_voice_parse_error,
    react_to_voice_success,
)


def test_greeting_kind():
    line = greeting('medium')
    assert line.kind == 'greeting'
    assert line.text


def test_game_over_kind():
    line = react_to_game_over('easy', result='checkmate', winner='human')
    assert line.kind == 'game_over'


def test_resign_game_over():
    line = react_to_game_over('medium', result='resign', winner='robot')
    assert line.kind == 'game_over'
    assert '기권' in line.text


def test_bot_move_uses_check_not_janggun():
    line = react_to_bot_move('easy', is_capture=False, is_check=True)
    assert line.kind == 'check'
    assert '체크' in line.text
    assert '장군' not in line.text


def test_player_check_uses_check_term():
    line = react_to_player_move(
        'easy',
        quality='good',
        is_capture=False,
        is_check=True,
        san='Qh5+',
    )
    assert line.kind == 'check'
    assert '장군' not in line.text


def test_player_move_check_priority():
    line = react_to_player_move(
        'medium',
        quality='good',
        is_capture=True,
        is_check=True,
        san='Qh5+',
    )
    assert line.kind == 'check'


def test_player_move_capture_kind():
    line = react_to_player_move(
        'medium',
        quality='mistake',
        is_capture=True,
        is_check=False,
        san='Bxf7',
    )
    assert line.kind == 'capture'


def test_player_move_routine_kind():
    line = react_to_player_move(
        'medium',
        quality='good',
        is_capture=False,
        is_check=False,
        san='e4',
    )
    assert line.kind == 'move'


def test_bot_move_check_kind():
    line = react_to_bot_move('medium', is_capture=False, is_check=True)
    assert line.kind == 'check'


def test_bot_move_capture_easy():
    line = react_to_bot_move('easy', is_capture=True, is_check=False)
    assert line.kind == 'capture'


def test_bot_move_routine():
    line = react_to_bot_move('hard', is_capture=False, is_check=False)
    assert line.kind == 'move'


def test_illegal_move_kind():
    line = react_to_illegal_move('medium', from_sq='e2', to_sq='c4')
    assert line.kind == 'illegal_move'
    assert any(word in line.text for word in ('규칙', '불법', '안 돼'))


def test_illegal_move_reverted_kind():
    line = react_to_illegal_move_reverted('easy')
    assert line.kind == 'illegal_move'
    assert any(word in line.text for word in ('되돌렸', '돌렸'))


def test_voice_move_parse_error_kind():
    line = react_to_voice_parse_error('medium')
    assert line.kind == 'voice_move'
    assert any(word in line.text for word in ('a2 a3', '출발 칸', '말해'))


def test_voice_move_success_kind():
    line = react_to_voice_success('easy', from_sq='e2', to_sq='e4')
    assert line.kind == 'voice_move'
    assert 'e2' in line.text


def test_voice_move_illegal_kind():
    line = react_to_voice_illegal('hard', from_sq='e2', to_sq='e5')
    assert line.kind == 'voice_move'
    assert '불법' in line.text
