"""Tests for robot turn and piece-color guards."""

from __future__ import annotations

import chess

from chess_robot_motion.graveyard_sides import robot_chess_color


def is_robot_turn(human_color: str, fen: str) -> bool:
    board = chess.Board(fen)
    robot_is_white = robot_chess_color(human_color) == 'white'
    return board.turn == chess.WHITE if robot_is_white else board.turn == chess.BLACK


def piece_symbol_is_robot(human_color: str, symbol: str | None) -> bool:
    if not symbol:
        return False
    robot_white = robot_chess_color(human_color) == 'white'
    return symbol.isupper() == robot_white


def test_human_white_start_is_not_robot_turn():
    fen = chess.STARTING_FEN
    assert not is_robot_turn('white', fen)


def test_human_white_after_e2e4_is_robot_turn():
    board = chess.Board()
    board.push_uci('e2e4')
    assert is_robot_turn('white', board.fen())


def test_human_black_start_is_robot_turn():
    fen = chess.STARTING_FEN
    assert is_robot_turn('black', fen)


def test_robot_rejects_human_piece_on_robot_turn():
    board = chess.Board()
    board.push_uci('e2e4')
    fen = board.fen()
    assert is_robot_turn('white', fen)
    assert not piece_symbol_is_robot('white', 'P')


def test_robot_accepts_robot_piece_on_robot_turn():
    board = chess.Board()
    board.push_uci('e2e4')
    fen = board.fen()
    assert piece_symbol_is_robot('white', board.piece_at(chess.E7).symbol())


def test_human_turn_rejects_robot_piece_move():
    board = chess.Board()
    assert not is_robot_turn('white', board.fen())
    piece = board.piece_at(chess.E7)
    assert piece is not None
    assert piece_symbol_is_robot('white', piece.symbol())
