"""Tests for bot banter speech kinds."""

from chess_web_ui.bot_banter import (
    greeting,
    react_to_bot_move,
    react_to_game_over,
    react_to_player_move,
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
    assert '체크메이트' in line.text


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
