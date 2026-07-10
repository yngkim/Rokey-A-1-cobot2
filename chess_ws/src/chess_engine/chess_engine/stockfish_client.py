"""Stockfish wrapper with difficulty presets, evaluation, and move classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import chess
import chess.engine

Difficulty = Literal['beginner', 'easy', 'medium', 'hard', 'master']

DIFFICULTY_PRESETS: dict[Difficulty, dict[str, object]] = {
    'beginner': {
        'limit_strength': True,
        'uci_elo': 700,
        'skill_level': 1,
        'depth': 6,
    },
    'easy': {
        'limit_strength': True,
        'uci_elo': 900,
        'skill_level': 3,
        'depth': 8,
    },
    'medium': {
        'limit_strength': True,
        'uci_elo': 1500,
        'skill_level': 10,
        'depth': 12,
    },
    'hard': {
        'limit_strength': True,
        'uci_elo': 2000,
        'skill_level': 15,
        'depth': 15,
    },
    'master': {
        'limit_strength': False,
        'uci_elo': 0,
        'skill_level': 20,
        'depth': 18,
    },
}

MATE_CP = 10000


@dataclass
class MoveClassification:
    best_uci: str
    cp_loss: int
    quality: str  # brilliant | good | inaccuracy | mistake | blunder


class StockfishClient:
    def __init__(self, engine_path: str = 'stockfish', depth: int = 10) -> None:
        self.engine_path = engine_path
        self.depth = depth
        self._difficulty: Difficulty = 'medium'
        self._engine: chess.engine.SimpleEngine | None = None
        self._engine_available = True

    def start(self) -> None:
        if self._engine is None:
            self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)

    def stop(self) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def configure_opponent(self, difficulty: Difficulty) -> None:
        self._difficulty = difficulty
        preset = DIFFICULTY_PRESETS[difficulty]
        self.depth = int(preset['depth'])
        if not self._engine_available:
            return
        try:
            self.start()
            assert self._engine is not None
            if preset['limit_strength']:
                self._engine.configure({
                    'UCI_LimitStrength': True,
                    'UCI_Elo': int(preset['uci_elo']),
                    'Skill Level': int(preset['skill_level']),
                })
            else:
                self._engine.configure({
                    'UCI_LimitStrength': False,
                    'Skill Level': int(preset['skill_level']),
                })
        except (FileNotFoundError, chess.engine.EngineError):
            self._engine_available = False

    def best_move_uci(self, fen: str) -> str:
        return self.choose_move(fen)

    def choose_move(self, fen: str) -> str:
        board = chess.Board(fen)
        if board.is_game_over():
            raise RuntimeError('game is over; no legal moves')
        preset = DIFFICULTY_PRESETS[self._difficulty]
        depth = int(preset['depth'])
        try:
            self.start()
            assert self._engine is not None
            self.configure_opponent(self._difficulty)
            result = self._engine.play(board, chess.engine.Limit(depth=depth))
            if result.move is None:
                raise RuntimeError('engine returned no move')
            return result.move.uci()
        except (FileNotFoundError, chess.engine.EngineError):
            self._engine_available = False
            legal_moves = list(board.legal_moves)
            if not legal_moves:
                raise RuntimeError('no legal moves available') from None
            return legal_moves[0].uci()

    def _score_to_cp(self, score: chess.engine.PovScore, *, white_perspective: bool = True) -> int:
        cp = score.white().score(mate_score=MATE_CP)
        if cp is None:
            return 0
        return int(cp)

    def evaluate(self, fen: str, *, depth: int = 12) -> int:
        """Return centipawn evaluation from White's perspective."""
        board = chess.Board(fen)
        try:
            self.start()
            assert self._engine is not None
            info = self._engine.analyse(board, chess.engine.Limit(depth=depth))
            return self._score_to_cp(info['score'])
        except (FileNotFoundError, chess.engine.EngineError):
            self._engine_available = False
            return 0

    def _eval_for_side(self, fen: str, *, depth: int = 12) -> int:
        """Evaluation from the side-to-move perspective."""
        board = chess.Board(fen)
        white_cp = self.evaluate(fen, depth=depth)
        if board.turn == chess.WHITE:
            return white_cp
        return -white_cp

    def _best_move_uci_analyse(self, fen: str, *, depth: int = 12) -> str:
        board = chess.Board(fen)
        try:
            self.start()
            assert self._engine is not None
            saved = self._difficulty
            if self._engine_available:
                self._engine.configure({'UCI_LimitStrength': False})
            info = self._engine.analyse(board, chess.engine.Limit(depth=depth))
            pv = info.get('pv') or []
            if pv:
                self.configure_opponent(saved)
                return pv[0].uci()
            result = self._engine.play(board, chess.engine.Limit(depth=depth))
            self.configure_opponent(saved)
            if result.move is not None:
                return result.move.uci()
        except (FileNotFoundError, chess.engine.EngineError):
            self._engine_available = False
        legal_moves = list(board.legal_moves)
        if not legal_moves:
            raise RuntimeError('no legal moves available')
        return legal_moves[0].uci()

    def classify_move(self, fen_before: str, played_uci: str, *, depth: int = 12) -> MoveClassification:
        board = chess.Board(fen_before)
        try:
            move = chess.Move.from_uci(played_uci)
        except ValueError:
            return MoveClassification(best_uci='', cp_loss=0, quality='good')

        best_uci = self._best_move_uci_analyse(fen_before, depth=depth)
        if played_uci == best_uci:
            return MoveClassification(best_uci=best_uci, cp_loss=0, quality='good')

        before_cp = self._eval_for_side(fen_before, depth=depth)
        try:
            board.push(move)
            after_cp = self._eval_for_side(board.fen(), depth=depth)
        except (ValueError, AssertionError):
            return MoveClassification(best_uci=best_uci, cp_loss=0, quality='good')

        cp_loss = max(0, before_cp - after_cp)
        quality = _quality_from_cp_loss(cp_loss)
        return MoveClassification(best_uci=best_uci, cp_loss=cp_loss, quality=quality)


def _quality_from_cp_loss(cp_loss: int) -> str:
    if cp_loss >= 300:
        return 'blunder'
    if cp_loss >= 150:
        return 'mistake'
    if cp_loss >= 60:
        return 'inaccuracy'
    if cp_loss <= 0:
        return 'brilliant'
    return 'good'
