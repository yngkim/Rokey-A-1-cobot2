from chess_web_ui.board_correct_utils import infer_human_move_uci

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def test_infer_human_move_after_e4() -> None:
    after = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
    assert infer_human_move_uci(START, after, 'white') == 'e2e4'


def test_infer_human_move_ignores_wrong_turn_toggle() -> None:
    # User left active color as white even though pieces show e4 was played.
    after_wrong_turn = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
    assert infer_human_move_uci(START, after_wrong_turn, 'white') == 'e2e4'


def test_infer_human_move_none_when_not_human_turn() -> None:
    after = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
    assert infer_human_move_uci(after, START, 'white') is None


def test_infer_human_move_none_when_ambiguous() -> None:
    assert infer_human_move_uci(START, START, 'white') is None
