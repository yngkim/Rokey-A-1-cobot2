"""Map YOLO detections to square/piece board estimates."""

from __future__ import annotations

import re

import chess

from chess_game.board_utils import index_to_square_name, occupancy_from_fen, square_name_to_index
from chess_web_ui.board_twin.calibration import SideViewSquareMapper
from chess_web_ui.board_twin.types import SideDetectionView, SideViewBoardEstimate

_CLASS_TO_SYMBOL: dict[str, str] = {
    'white-pawn': 'P',
    'white-knight': 'N',
    'white-bishop': 'B',
    'white-rook': 'R',
    'white-queen': 'Q',
    'white-king': 'K',
    'black-pawn': 'p',
    'black-knight': 'n',
    'black-bishop': 'b',
    'black-rook': 'r',
    'black-queen': 'q',
    'black-king': 'k',
    'white_pawn': 'P',
    'white_knight': 'N',
    'white_bishop': 'B',
    'white_rook': 'R',
    'white_queen': 'Q',
    'white_king': 'K',
    'black_pawn': 'p',
    'black_knight': 'n',
    'black_bishop': 'b',
    'black_rook': 'r',
    'black_queen': 'q',
    'black_king': 'k',
    'wp': 'P',
    'wn': 'N',
    'wb': 'B',
    'wr': 'R',
    'wq': 'Q',
    'wk': 'K',
    'bp': 'p',
    'bn': 'n',
    'bb': 'b',
    'br': 'r',
    'bq': 'q',
    'bk': 'k',
}


def class_name_to_symbol(class_name: str) -> str:
    token = (class_name or '').strip().lower().replace(' ', '_')
    if token in _CLASS_TO_SYMBOL:
        return _CLASS_TO_SYMBOL[token]
    if len(token) == 1 and token in 'prnbqkPRNBQK':
        return token.upper() if token.isupper() else token
    match = re.match(r'^(white|black)[-_]?(pawn|knight|bishop|rook|queen|king)$', token)
    if match:
        color = 'upper' if match.group(1) == 'white' else 'lower'
        piece = {
            'pawn': 'P',
            'knight': 'N',
            'bishop': 'B',
            'rook': 'R',
            'queen': 'Q',
            'king': 'K',
        }[match.group(2)]
        return piece if color == 'upper' else piece.lower()
    return ''


def piece_map_to_placement_fen(piece_map: dict[str, str]) -> str:
    board = chess.Board(None)
    for square_name, symbol in piece_map.items():
        try:
            square = chess.parse_square(square_name)
        except ValueError:
            continue
        piece = chess.Piece.from_symbol(symbol)
        board.set_piece_at(square, piece)
    return board.board_fen()


def merge_recorded_metadata(placement_fen: str, recorded_fen: str) -> str:
    recorded = chess.Board(recorded_fen)
    parts = recorded_fen.split()
    active = parts[1] if len(parts) > 1 else 'w'
    castling = parts[2] if len(parts) > 2 else '-'
    ep = parts[3] if len(parts) > 3 else '-'
    halfmove = parts[4] if len(parts) > 4 else '0'
    fullmove = parts[5] if len(parts) > 5 else '1'
    return f'{placement_fen} {active} {castling} {ep} {halfmove} {fullmove}'


def normalize_side_detections(
    detections: list[object],
    mapper: SideViewSquareMapper,
    *,
    recorded_fen: str = '',
) -> SideViewBoardEstimate:
    views: list[SideDetectionView] = []
    square_candidates: dict[str, list[tuple[str, float, SideDetectionView]]] = {}
    unmapped = 0

    for det in detections:
        class_name = str(getattr(det, 'class_name', ''))
        symbol = class_name_to_symbol(class_name)
        center = getattr(det, 'center', (0.0, 0.0))
        score = float(getattr(det, 'score', 0.0))
        raw_bbox = getattr(det, 'bbox', (0.0, 0.0, 0.0, 0.0))
        bbox = tuple(float(v) for v in raw_bbox[:4]) if raw_bbox else (0.0, 0.0, 0.0, 0.0)
        square = mapper.image_to_square_name(float(center[0]), float(center[1]))
        view = SideDetectionView(
            class_name=class_name,
            symbol=symbol,
            square=square or '',
            confidence=score,
            center_x=float(center[0]),
            center_y=float(center[1]),
            bbox=bbox,
        )
        views.append(view)
        if not square or not symbol:
            unmapped += 1
            continue
        square_candidates.setdefault(square, []).append((symbol, score, view))

    piece_map: dict[str, str] = {}
    duplicate_squares: list[str] = []
    for square, candidates in square_candidates.items():
        candidates.sort(key=lambda item: item[1], reverse=True)
        piece_map[square] = candidates[0][0]
        if len(candidates) > 1:
            duplicate_squares.append(square)

    occupancy = [False] * 64
    for square in piece_map:
        occupancy[square_name_to_index(square)] = True

    placement = piece_map_to_placement_fen(piece_map)
    candidate_fen = merge_recorded_metadata(placement, recorded_fen) if recorded_fen else placement

    return SideViewBoardEstimate(
        piece_map=piece_map,
        occupancy=occupancy,
        placement_fen=candidate_fen,
        detections=views,
        duplicate_squares=duplicate_squares,
        unmapped_detections=unmapped,
        message=f'{len(piece_map)} squares mapped from {len(views)} detections',
    )


def occupancy_adjusted_fen(recorded_fen: str, realsense_occupancy: list[bool]) -> str:
    """Apply RealSense occupancy to recorded FEN (removals only; RS is authoritative)."""
    board = chess.Board(recorded_fen)
    for idx in range(64):
        sensed_has = realsense_occupancy[idx] if idx < len(realsense_occupancy) else False
        if sensed_has:
            continue
        board.remove_piece_at(chess.SQUARES[idx])
    return board.fen()


def recorded_piece_map(fen: str) -> dict[str, str]:
    board = chess.Board(fen)
    out: dict[str, str] = {}
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is not None:
            out[chess.square_name(square)] = piece.symbol()
    return out


def occupancy_to_squares(cells: list[bool]) -> set[str]:
    return {index_to_square_name(idx) for idx, occupied in enumerate(cells) if occupied}
