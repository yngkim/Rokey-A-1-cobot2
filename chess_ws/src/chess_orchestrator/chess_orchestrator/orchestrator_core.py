"""Central game orchestrator."""

from __future__ import annotations

from chess_coach.coach import Coach
from chess_dialogue.dialogue import DialogueService
from chess_engine.stockfish_client import StockfishClient
from chess_game.game_state import GameState
from chess_game.move_matcher import MoveMatcher
from chess_orchestrator.game_phase import GamePhase


class OrchestratorCore:
    def __init__(self) -> None:
        self.phase = GamePhase.IDLE
        self.game = GameState()
        self.matcher = MoveMatcher()
        self.engine = StockfishClient()
        self.coach = Coach()
        self.dialogue = DialogueService()
        self.previous_cells: list[bool] | None = None

    def start_new_game(self, mode: int = GameState.MODE_MATCH) -> None:
        self.game = GameState()
        self.game.mode = mode
        self.previous_cells = None
        self.phase = GamePhase.GAME_SETUP

    def on_user_confirmed(self) -> None:
        if self.phase == GamePhase.WAIT_USER_MOVE:
            self.phase = GamePhase.SCANNING_USER

    def apply_scan(self, cells: list[bool]) -> None:
        if self.phase == GamePhase.SCANNING_USER:
            self._validate_user_move(cells)
        elif self.phase in {GamePhase.SCANNING_ROBOT, GamePhase.GAME_SETUP}:
            self.previous_cells = list(cells)
            if self.phase == GamePhase.GAME_SETUP:
                self.phase = GamePhase.WAIT_USER_MOVE
            else:
                self.phase = GamePhase.WAIT_USER_MOVE

    def _validate_user_move(self, cells: list[bool]) -> None:
        if self.previous_cells is None:
            self.previous_cells = cells
            self.phase = GamePhase.WAIT_USER_MOVE
            return

        result = self.matcher.match_from_occupancy(
            self.game.fen,
            self.previous_cells,
            cells,
        )
        if result.matched and result.best:
            fen_before = self.game.fen
            self.game.apply_uci(result.best)
            self.previous_cells = list(cells)
            if self.game.mode == GameState.MODE_COACH:
                self.coach.evaluate_move(fen_before, result.best)
            self.phase = GamePhase.ROBOT_PLANNING
        else:
            self.phase = GamePhase.UI_CONFIRM

    def plan_robot_move(self) -> str:
        self._pending_robot_move = self.engine.best_move_uci(self.game.fen)
        self.phase = GamePhase.ROBOT_EXECUTING
        return self._pending_robot_move

    def on_robot_move_finished(self, success: bool) -> None:
        if success:
            if hasattr(self, '_pending_robot_move'):
                self.game.apply_uci(self._pending_robot_move)
            self.phase = GamePhase.SCANNING_ROBOT
        else:
            self.phase = GamePhase.ERROR

    def shutdown(self) -> None:
        self.engine.stop()
        self.coach.shutdown()
