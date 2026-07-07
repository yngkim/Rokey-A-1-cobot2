"""Tests for move_resolve helpers."""

from __future__ import annotations

import chess
import pytest

from chess_game.move_resolve import (
    captured_piece_symbol,
    game_outcome,
    resolve_legal_uci,
    resolve_legal_uci_full,
)


def test_en_passant_resolve_and_capture() -> None:
    fen = 'rnbqkbnr/pp2pppp/8/2ppP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3'
    uci = resolve_legal_uci(fen, 'e5', 'd6')
    assert uci == 'e5d6'
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    assert captured_piece_symbol(board, move) == 'p'


def test_promotion_requires_explicit_piece() -> None:
    fen = '8/4P3/8/8/8/8/8/4K2k w - - 0 1'
    assert resolve_legal_uci(fen, 'e7', 'e8') is None
    assert resolve_legal_uci(fen, 'e7', 'e8', promotion=chess.QUEEN) == 'e7e8q'


def test_promotion_full_uci() -> None:
    fen = '8/4P3/8/8/8/8/8/4K2k w - - 0 1'
    assert resolve_legal_uci_full('e7e8r', fen) == 'e7e8r'


def test_checkmate_outcome() -> None:
    fen = 'rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3'
    outcome = game_outcome(chess.Board(fen))
    assert outcome.is_over
    assert outcome.reason == 'checkmate'
    assert outcome.result == '0-1'
    assert outcome.winner_side == 'black'


def test_stalemate_outcome() -> None:
    fen = '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1'
    outcome = game_outcome(chess.Board(fen))
    assert outcome.is_over
    assert outcome.reason == 'stalemate'
    assert outcome.winner_side == 'draw'


def test_illegal_move_returns_none() -> None:
    fen = chess.STARTING_FEN
    assert resolve_legal_uci(fen, 'e2', 'e5') is None
