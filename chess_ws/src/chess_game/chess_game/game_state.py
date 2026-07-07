"""Game state wrapper around python-chess."""

from __future__ import annotations

import chess

from chess_game.move_resolve import GameOutcome, game_outcome


class GameState:
    MODE_MATCH = 0
    MODE_COACH = 1
    MODE_DIALOGUE = 2

    def __init__(self, fen: str | None = None) -> None:
        self.board = chess.Board(fen or chess.STARTING_FEN)
        self.mode = self.MODE_MATCH
        self.move_number = 1

    @property
    def fen(self) -> str:
        return self.board.fen()

    @property
    def white_to_move(self) -> bool:
        return self.board.turn == chess.WHITE

    def apply_uci(self, uci: str) -> None:
        self.board.push_uci(uci)
        self.move_number = self.board.fullmove_number

    def is_game_over(self) -> bool:
        return self.board.is_game_over()

    def outcome(self) -> GameOutcome:
        return game_outcome(self.board)

    def apply_vision_move(self, from_square: str, to_square: str) -> bool:
        """Debug-only: update board ignoring chess rules. Not used in production."""
        try:
            from_idx = chess.parse_square(from_square)
            to_idx = chess.parse_square(to_square)
        except ValueError:
            return False

        piece = self.board.piece_at(from_idx)
        if piece is None:
            piece = self._guess_piece_for_square(from_idx)
        if piece is None:
            return False

        self.board.remove_piece_at(from_idx)
        self.board.set_piece_at(to_idx, piece)
        self.board.turn = not self.board.turn
        return True

    def _guess_piece_for_square(self, square: int) -> chess.Piece | None:
        rank = chess.square_rank(square)
        if rank == 1:
            return chess.Piece(chess.PAWN, chess.WHITE)
        if rank == 6:
            return chess.Piece(chess.PAWN, chess.BLACK)
        return None

    def legal_moves_uci(self) -> list[str]:
        return [move.uci() for move in self.board.legal_moves]
