"""Tests for capture symbol resolution."""

from chess_web_ui.capture_utils import resolve_capture_symbol

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def test_resolve_capture_ignores_hint_on_non_capture():
    assert resolve_capture_symbol(START, 'e2e4', 'p') == ''


def test_resolve_capture_uses_hint_on_real_capture():
    fen = 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2'
    assert resolve_capture_symbol(fen, 'e4d5', 'p') == 'p'


def test_resolve_capture_falls_back_to_inferred():
    fen = 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2'
    assert resolve_capture_symbol(fen, 'e4d5', 'invalid') == 'p'
