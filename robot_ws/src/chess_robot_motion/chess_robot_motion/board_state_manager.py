"""In-memory chess board occupancy and FEN for manual pick-place testing."""

from __future__ import annotations

from dataclasses import dataclass

from chess_robot_motion.occupancy_grid import STARTING_FEN, starting_occupancy
from chess_robot_motion.square_pose_map import SquareCoord, square_to_index, uci_to_square


@dataclass
class MoveValidation:
    ok: bool
    message: str
    is_capture: bool = False


class BoardStateManager:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.cells = starting_occupancy()
        self.fen = STARTING_FEN

    def has_piece(self, col: int, row: int) -> bool:
        return self.cells[square_to_index(col, row)]

    def validate_move(self, from_sq: SquareCoord, to_sq: SquareCoord) -> MoveValidation:
        if from_sq.col == to_sq.col and from_sq.row == to_sq.row:
            return MoveValidation(False, 'from and to squares are the same')
        if not self.has_piece(from_sq.col, from_sq.row):
            return MoveValidation(False, f'no piece at {self._sq_name(from_sq)}')
        is_capture = self.has_piece(to_sq.col, to_sq.row)
        return MoveValidation(True, 'ok', is_capture=is_capture)

    def validate_uci(self, from_uci: str, to_uci: str) -> MoveValidation:
        return self.validate_move(uci_to_square(from_uci), uci_to_square(to_uci))

    def apply_move(self, from_sq: SquareCoord, to_sq: SquareCoord) -> None:
        validation = self.validate_move(from_sq, to_sq)
        if not validation.ok:
            raise ValueError(validation.message)

        from_idx = square_to_index(from_sq.col, from_sq.row)
        to_idx = square_to_index(to_sq.col, to_sq.row)
        self.cells[to_idx] = True
        self.cells[from_idx] = False
        self.fen = self._apply_move_to_fen(self.fen, from_sq, to_sq)

    def apply_uci_move(self, from_uci: str, to_uci: str) -> None:
        self.apply_move(uci_to_square(from_uci), uci_to_square(to_uci))

    @staticmethod
    def _sq_name(sq: SquareCoord) -> str:
        return f'{chr(ord("a") + sq.col)}{sq.row + 1}'

    @staticmethod
    def _apply_move_to_fen(fen: str, from_sq: SquareCoord, to_sq: SquareCoord) -> str:
        board_rows = fen.split(' ')[0].split('/')
        grid: list[list[str | None]] = []
        for row_str in board_rows:
            row_cells: list[str | None] = []
            for ch in row_str:
                if ch.isdigit():
                    row_cells.extend([None] * int(ch))
                else:
                    row_cells.append(ch)
            grid.append(row_cells)

        from_row = 7 - from_sq.row
        to_row = 7 - to_sq.row
        piece = grid[from_row][from_sq.col]
        grid[from_row][from_sq.col] = None
        grid[to_row][to_sq.col] = piece

        fen_rows: list[str] = []
        for row in grid:
            empty = 0
            row_str = ''
            for cell in row:
                if cell is None:
                    empty += 1
                else:
                    if empty:
                        row_str += str(empty)
                        empty = 0
                    row_str += cell
            if empty:
                row_str += str(empty)
            fen_rows.append(row_str or '8')

        tail = fen.split(' ', 1)[1] if ' ' in fen else 'w KQkq - 0 1'
        return f"{'/'.join(fen_rows)} {tail}"
