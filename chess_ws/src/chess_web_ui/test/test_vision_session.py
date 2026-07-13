"""Tests for vision session move detection."""

import chess

from chess_game.board_utils import occupancy_from_fen
from chess_game.game_state import GameState
from chess_web_ui.vision_session import VisionSession


def _starting_cells() -> list[bool]:
    cells = [False] * 64
    for idx in range(16):
        cells[idx] = True
    for idx in range(48, 64):
        cells[idx] = True
    return cells


def test_initial_scan_sets_baseline() -> None:
    session = VisionSession()
    cells = _starting_cells()
    outcome = session.apply_initial_scan(cells)
    assert outcome.success
    assert session.previous_cells == cells


def test_detect_e2e4() -> None:
    session = VisionSession()
    before = _starting_cells()
    session.apply_initial_scan(before)

    after = list(before)
    after[12] = False  # e2
    after[28] = True   # e4
    outcome = session.apply_player_move_scan(after)
    assert outcome.success
    assert outcome.from_square == 'e2'
    assert outcome.to_square == 'e4'


def test_detect_e2e4_when_e2_still_reads_occupied() -> None:
    """Depth noise: e2 may stay occupied; e4 arrival plus e2 departure still detects e2e4."""
    session = VisionSession()
    before = _starting_cells()
    session.apply_initial_scan(before)

    after = list(before)
    after[12] = False  # e2
    after[28] = True   # e4
    outcome = session.apply_player_move_scan(after)
    assert outcome.success
    assert outcome.from_square == 'e2'
    assert outcome.to_square == 'e4'


def test_no_move_when_unchanged_scan() -> None:
    session = VisionSession()
    before = _starting_cells()
    session.apply_initial_scan(before)
    fen_before = session.game.fen

    outcome = session.apply_player_move_scan(list(before))
    assert not outcome.success
    assert 'no move detected' in outcome.message
    assert session.game.fen == fen_before


def test_detect_d7d5_when_d7_still_reads_occupied() -> None:
    session = VisionSession()
    before = _starting_cells()
    session.apply_initial_scan(before)

    after_white = list(before)
    after_white[12] = False
    after_white[28] = True
    session.apply_player_move_scan(after_white)

    after = list(session.previous_cells or after_white)
    after[51] = False  # d7
    after[35] = True   # d5
    outcome = session.apply_player_move_scan(after)
    assert outcome.success
    assert outcome.from_square == 'd7'
    assert outcome.to_square == 'd5'
    board = chess.Board(outcome.fen)
    assert board.piece_at(chess.parse_square('d5')) is not None
    assert board.piece_at(chess.parse_square('d7')) is None


def test_detect_d7d5_after_e2e4() -> None:
    session = VisionSession()
    before = _starting_cells()
    session.apply_initial_scan(before)

    after_white = list(before)
    after_white[12] = False
    after_white[28] = True
    session.apply_player_move_scan(after_white)

    after_black = list(after_white)
    after_black[51] = False
    after_black[35] = True
    outcome = session.apply_player_move_scan(after_black)
    assert outcome.success
    assert outcome.from_square == 'd7'
    assert outcome.to_square == 'd5'
    board = chess.Board(outcome.fen)
    assert board.piece_at(chess.parse_square('d7')) is None
    assert board.piece_at(chess.parse_square('d5')) is not None


def test_apply_robot_move_updates_occupancy() -> None:
    session = VisionSession()
    before = _starting_cells()
    session.apply_initial_scan(before)

    after = list(before)
    after[12] = False  # e2
    after[28] = True   # e4
    session.apply_player_move_scan(after)

    outcome = session.apply_robot_move(4, 6, 4, 4)  # e7 -> e5
    assert outcome.success
    assert session.previous_cells is not None
    assert session.previous_cells[52] is False
    assert session.previous_cells[36] is True


def test_set_board_from_fen_syncs_occupancy() -> None:
    from chess_game.board_utils import occupancy_from_fen

    session = VisionSession()
    session.apply_initial_scan(_starting_cells())

    custom_fen = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2'
    outcome = session.set_board_from_fen(custom_fen)
    assert outcome.success
    assert session.game.fen == custom_fen
    assert session.previous_cells == occupancy_from_fen(custom_fen)


def test_false_positive_on_empty_square_ignored_with_low_confidence() -> None:
    session = VisionSession()
    session.apply_initial_scan(_starting_cells())

    after = list(_starting_cells())
    after[12] = False  # e2
    after[28] = True   # e4
    after[27] = True   # d4 noise
    confidence = [0.8 if occupied else 0.0 for occupied in after]
    confidence[28] = 0.8
    confidence[27] = 0.1

    outcome = session.apply_player_move_scan(after, confidence=confidence)
    assert outcome.success
    assert outcome.from_square == 'e2'
    assert outcome.to_square == 'e4'
    assert session.previous_cells == occupancy_from_fen(outcome.fen)


def test_fen_snap_baseline_after_move() -> None:
    session = VisionSession()
    session.apply_initial_scan(_starting_cells())

    after = list(_starting_cells())
    after[12] = False
    after[28] = True
    session.apply_player_move_scan(after)

    assert session.previous_cells == occupancy_from_fen(session.game.fen)


def test_illegal_move_rejected() -> None:
    session = VisionSession()
    before = _starting_cells()
    session.apply_initial_scan(before)
    fen_before = session.game.fen

    after = list(before)
    after[12] = False  # e2
    after[26] = True   # c4 (illegal pawn move)
    outcome = session.apply_player_move_scan(after)
    assert not outcome.success
    assert outcome.from_square == 'e2'
    assert outcome.to_square == 'c4'
    assert session.game.fen == fen_before


def test_promotion_requires_ui_choice() -> None:
    session = VisionSession()
    fen = '8/4P3/8/8/8/8/8/4K2k w - - 0 1'
    session.game = GameState(fen)
    session.previous_cells = occupancy_from_fen(fen)

    after = occupancy_from_fen(fen)
    after[chess.square_file(chess.E7) + chess.square_rank(chess.E7) * 8] = False
    after[chess.square_file(chess.E8) + chess.square_rank(chess.E8) * 8] = True
    outcome = session.apply_player_move_scan(after)
    assert not outcome.success
    assert outcome.promotion_required
    assert outcome.message == 'promotion_required'
    assert session.game.fen == fen

    promoted = session.apply_player_promotion('e7', 'e8', 'q')
    assert promoted.success
    board = chess.Board(promoted.fen)
    piece = board.piece_at(chess.E8)
    assert piece is not None
    assert piece.piece_type == chess.QUEEN
    assert promoted.promotion_piece == 'q'


def test_detect_move_with_a2_ghost_departed() -> None:
    """Stale a2 departed noise must not block a real e7→e5 black move."""
    fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
    session = VisionSession()
    session.game = GameState(fen)
    baseline = occupancy_from_fen(fen)
    session.previous_cells = list(baseline)

    after = list(baseline)
    a2 = chess.square(0, 1)
    e7 = chess.square(4, 6)
    e5 = chess.square(4, 4)
    after[a2] = False  # ghost: scan says a2 empty though FEN still has pawn
    after[e7] = False
    after[e5] = True

    outcome = session.apply_player_move_scan(after)
    assert outcome.success
    assert outcome.from_square == 'e7'
    assert outcome.to_square == 'e5'


def test_detect_single_square_capture_with_no_arrived_square() -> None:
    """A capture onto a square that stays occupied the whole time (piece taken,
    capturer arrives) never produces an "arrived" signal. This used to get
    pruned as depth-sensor noise because the pre-move FEN always still shows a
    piece at the departed square — true for every real move, not just ghosts —
    silently dropping every single-square capture (e.g. Nxb4) as "no move
    detected"."""
    fen = '4k3/8/2n5/8/1P6/8/8/4K3 b - - 0 1'
    session = VisionSession()
    session.game = GameState(fen)
    baseline = occupancy_from_fen(fen)
    session.previous_cells = list(baseline)

    after = list(baseline)
    c6 = chess.square(2, 5)
    after[c6] = False  # knight departs c6; b4 (pawn captured, knight lands) stays occupied

    outcome = session.apply_player_move_scan(after)
    assert outcome.success
    assert outcome.from_square == 'c6'
    assert outcome.to_square == 'b4'
    assert outcome.captured_piece

