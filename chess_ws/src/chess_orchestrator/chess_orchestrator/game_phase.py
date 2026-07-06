"""Game orchestrator states."""

from enum import Enum, auto


class GamePhase(Enum):
    IDLE = auto()
    GAME_SETUP = auto()
    WAIT_USER_MOVE = auto()
    SCANNING_USER = auto()
    VALIDATING_USER_MOVE = auto()
    ROBOT_PLANNING = auto()
    ROBOT_EXECUTING = auto()
    SCANNING_ROBOT = auto()
    VALIDATING_ROBOT_MOVE = auto()
    UI_CONFIRM = auto()
    ERROR = auto()
