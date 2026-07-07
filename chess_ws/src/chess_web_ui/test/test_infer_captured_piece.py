"""Regression: vision noise must not invent captures."""

from chess_game.occupancy_diff import infer_captured_piece


START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def test_no_capture_on_normal_pawn_move() -> None:
    assert infer_captured_piece(START_FEN, 'e2', 'e4') == ''


def test_no_capture_when_noise_departed_extra_square() -> None:
    """Extra departed square with piece still on board is depth noise, not capture."""
    baseline = [False] * 64
    for idx in range(16):
        baseline[idx] = True
    for idx in range(48, 64):
        baseline[idx] = True

    captured = infer_captured_piece(
        START_FEN,
        'e2',
        'e4',
        departed=['e2', 'f2'],
        baseline=baseline,
    )
    assert captured == ''


def test_capture_on_legal_take() -> None:
    fen = 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2'
    assert infer_captured_piece(fen, 'e4', 'd5') == 'p'
