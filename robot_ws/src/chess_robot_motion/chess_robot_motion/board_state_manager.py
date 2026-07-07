"""In-memory chess board occupancy and FEN for manual pick-place testing."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_robot_motion.move_physics import move_physics_flags, resolve_legal_uci_full
from chess_robot_motion.occupancy_grid import STARTING_FEN, starting_occupancy
from chess_robot_motion.square_pose_map import SquareCoord, square_to_index, uci_to_square


@dataclass
class MoveValidation:
    ok: bool
    message: str
    is_capture: bool = False
    is_en_passant: bool = False
    is_castling: bool = False
    promotion: str = ''
    capture_col: int = 255
    capture_row: int = 255
    rook_from_col: int = 255
    rook_from_row: int = 255
    rook_to_col: int = 255
    rook_to_row: int = 255
    full_uci: str = ''


class BoardStateManager:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.cells = starting_occupancy()
        self.fen = STARTING_FEN

    def set_fen(self, fen: str) -> None:
        board = chess.Board(fen)
        self.fen = board.fen()
        self._sync_cells_from_board(board)

    def _sync_cells_from_board(self, board: chess.Board) -> None:
        self.cells = [False] * 64
        for square, _piece in board.piece_map().items():
            col = chess.square_file(square)
            row = chess.square_rank(square)
            self.cells[square_to_index(col, row)] = True

    def has_piece(self, col: int, row: int) -> bool:
        return self.cells[square_to_index(col, row)]

    def piece_at(self, col: int, row: int) -> str | None:
        grid = self._fen_grid()
        fen_row = 7 - row
        if not (0 <= fen_row < 8 and 0 <= col < 8):
            return None
        return grid[fen_row][col]

    def _fen_grid(self) -> list[list[str | None]]:
        board_rows = self.fen.split(' ')[0].split('/')
        grid: list[list[str | None]] = []
        for row_str in board_rows:
            row_cells: list[str | None] = []
            for ch in row_str:
                if ch.isdigit():
                    row_cells.extend([None] * int(ch))
                else:
                    row_cells.append(ch)
            grid.append(row_cells)
        return grid

    def validate_move(self, from_sq: SquareCoord, to_sq: SquareCoord) -> MoveValidation:
        from_name = self._sq_name(from_sq)
        to_name = self._sq_name(to_sq)
        return self.validate_uci(f'{from_name}{to_name}')

    def validate_uci(self, uci: str) -> MoveValidation:
        legal = resolve_legal_uci_full(uci, self.fen)
        if legal is None:
            return MoveValidation(False, f'illegal move {uci!r} for current FEN')

        board = chess.Board(self.fen)
        move = chess.Move.from_uci(legal)
        if move not in board.legal_moves:
            return MoveValidation(False, f'illegal move {legal!r}')

        flags = move_physics_flags(board, move)
        capture_col, capture_row = 255, 255
        cap_name = flags.get('capture_square')
        if isinstance(cap_name, str):
            cap_sq = chess.parse_square(cap_name)
            capture_col = chess.square_file(cap_sq)
            capture_row = chess.square_rank(cap_sq)

        rook_from_col = rook_from_row = rook_to_col = rook_to_row = 255
        rook_from = flags.get('rook_from')
        rook_to = flags.get('rook_to')
        if isinstance(rook_from, str) and isinstance(rook_to, str):
            rf = chess.parse_square(rook_from)
            rt = chess.parse_square(rook_to)
            rook_from_col = chess.square_file(rf)
            rook_from_row = chess.square_rank(rf)
            rook_to_col = chess.square_file(rt)
            rook_to_row = chess.square_rank(rt)

        from_sq = uci_to_square(legal[:2])
        if not self.has_piece(from_sq.col, from_sq.row):
            return MoveValidation(False, f'no piece at {legal[:2]}')

        return MoveValidation(
            True,
            'ok',
            is_capture=bool(flags['is_capture']),
            is_en_passant=bool(flags['is_en_passant']),
            is_castling=bool(flags['is_castling']),
            promotion=str(flags.get('promotion') or ''),
            capture_col=capture_col,
            capture_row=capture_row,
            rook_from_col=rook_from_col,
            rook_from_row=rook_from_row,
            rook_to_col=rook_to_col,
            rook_to_row=rook_to_row,
            full_uci=legal,
        )

    def apply_move(self, from_sq: SquareCoord, to_sq: SquareCoord) -> None:
        validation = self.validate_move(from_sq, to_sq)
        if not validation.ok:
            raise ValueError(validation.message)
        self.apply_uci(validation.full_uci)

    def apply_uci(self, uci: str) -> None:
        validation = self.validate_uci(uci)
        if not validation.ok:
            raise ValueError(validation.message)
        board = chess.Board(self.fen)
        board.push_uci(validation.full_uci)
        self.fen = board.fen()
        self._sync_cells_from_board(board)

    def apply_uci_move(self, from_uci: str, to_uci: str) -> None:
        self.apply_uci(f'{from_uci}{to_uci}')

    def remove_piece_at(self, col: int, row: int) -> str | None:
        piece = self.piece_at(col, row)
        if piece is None:
            return None
        idx = square_to_index(col, row)
        self.cells[idx] = False
        self.fen = self._set_square_in_fen(self.fen, col, row, None)
        return piece

    def put_piece_at(self, col: int, row: int, symbol: str) -> None:
        idx = square_to_index(col, row)
        self.cells[idx] = True
        self.fen = self._set_square_in_fen(self.fen, col, row, symbol)

    @staticmethod
    def _set_square_in_fen(fen: str, col: int, row: int, symbol: str | None) -> str:
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
        grid[7 - row][col] = symbol
        fen_rows: list[str] = []
        for fen_row in grid:
            empty = 0
            row_str = ''
            for cell in fen_row:
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

    @staticmethod
    def _sq_name(sq: SquareCoord) -> str:
        return f'{chr(ord("a") + sq.col)}{sq.row + 1}'
