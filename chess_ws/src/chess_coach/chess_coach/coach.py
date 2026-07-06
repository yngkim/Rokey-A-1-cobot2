"""Generate coaching feedback for a played move."""

from __future__ import annotations

from chess_msgs.msg import CoachFeedback
from chess_engine.stockfish_client import StockfishClient


class Coach:
    def __init__(self) -> None:
        self.engine = StockfishClient(depth=8)

    def evaluate_move(self, fen_before: str, played_uci: str) -> CoachFeedback:
        best_move = self.engine.best_move_uci(fen_before)
        feedback = CoachFeedback()
        feedback.evaluation_cp = 0.0
        feedback.best_move_uci = best_move
        if played_uci == best_move:
            feedback.hint = '좋은 수입니다.'
            feedback.spoken_text = '좋은 수입니다.'
        else:
            feedback.hint = f'다른 수도 고려해 보세요. 엔진 추천: {best_move}'
            feedback.spoken_text = feedback.hint
        return feedback

    def shutdown(self) -> None:
        self.engine.stop()
