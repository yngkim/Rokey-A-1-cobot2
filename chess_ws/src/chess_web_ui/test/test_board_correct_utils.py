from chess_web_ui.board_correct_utils import guard_correction_fen, infer_human_move_uci

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


def test_guard_correction_fen_restores_dropped_metadata() -> None:
    # Reproduces a real incident: a client-submitted FEN kept the exact same
    # placement but lost castling/halfmove/fullmove (e.g. buildFenFromGrid's
    # fallback), which desynced the move counter from move_history forever and
    # froze the robot (bot_fen_trustworthy rejected every retry indefinitely).
    good = 'rnbqkb1r/1p3ppp/p2ppn2/2pP4/2B1P3/2N5/PPP2PPP/R1BQK1NR w KQkq - 0 6'
    corrupted = 'rnbqkb1r/1p3ppp/p2ppn2/2pP4/2B1P3/2N5/PPP2PPP/R1BQK1NR w - - 0 1'
    assert guard_correction_fen(good, corrupted) == good


def test_guard_correction_fen_keeps_legitimate_edit() -> None:
    good = 'rnbqkb1r/1p3ppp/p2ppn2/2pP4/2B1P3/2N5/PPP2PPP/R1BQK1NR w KQkq - 0 6'
    edited = 'rnbqkb1r/1p3ppp/pB1ppn2/2pP4/4P3/2N5/PPP2PPP/R1BQK1NR b KQkq - 0 6'
    assert guard_correction_fen(good, edited) == edited


def test_guard_correction_fen_keeps_forward_progress() -> None:
    # A genuinely later position (higher fullmove) must pass through untouched.
    good = 'rnbqkb1r/1p3ppp/p2ppn2/2pP4/2B1P3/2N5/PPP2PPP/R1BQK1NR w KQkq - 0 6'
    later = 'r1bqkb1r/1p3ppp/p1nppn2/2pP4/2B1P3/2N5/PPP2PPP/R1BQK1NR w KQkq - 2 8'
    assert guard_correction_fen(good, later) == later
