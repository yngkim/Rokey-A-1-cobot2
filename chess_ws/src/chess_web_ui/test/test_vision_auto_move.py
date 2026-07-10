import chess

from chess_game.move_resolve import resolve_legal_uci_full
from chess_web_ui.vision_session import ScanOutcome
from chess_web_ui.web_bridge import parse_auto_move_game_id


def _uci_promo_variants(uci: str) -> list[str]:
    uci = (uci or '').strip().lower()
    if len(uci) > 4:
        return [uci]
    return [f'{uci[:4]}{promo}' for promo in ('', 'q', 'r', 'b', 'n')]


def _undo_move_on_after_board(after: chess.Board, uci: str) -> chess.Board | None:
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    piece = after.piece_at(move.to_square)
    if piece is None:
        return None
    board = after.copy()
    board.remove_piece_at(move.to_square)
    rank = chess.square_rank(move.from_square)

    if board.is_en_passant(move):
        cap_sq = chess.square(
            chess.square_file(move.to_square),
            rank + (1 if piece.color == chess.WHITE else -1),
        )
        board.set_piece_at(move.from_square, chess.Piece(chess.PAWN, piece.color))
        board.set_piece_at(cap_sq, chess.Piece(chess.PAWN, not piece.color))
        board.turn = not after.turn
        return board
    if board.is_castling(move):
        board.set_piece_at(move.from_square, piece)
        if move.to_square == chess.square(6, rank):
            rook = board.remove_piece_at(chess.square(5, rank))
            if rook is not None:
                board.set_piece_at(chess.square(7, rank), rook)
        elif move.to_square == chess.square(2, rank):
            rook = board.remove_piece_at(chess.square(3, rank))
            if rook is not None:
                board.set_piece_at(chess.square(0, rank), rook)
        board.turn = not after.turn
        return board
    else:
        if move.promotion:
            board.set_piece_at(move.from_square, chess.Piece(chess.PAWN, piece.color))
        else:
            board.set_piece_at(move.from_square, piece)
        board.turn = not after.turn
        resolved = resolve_legal_uci_full(uci, board.fen())
        if resolved:
            check = chess.Board(board.fen())
            check.push_uci(resolved)
            if check.board_fen() == after.board_fen() and check.turn == after.turn:
                return board

        board.remove_piece_at(move.from_square)
        cap_color = not piece.color
        for piece_type in (chess.PAWN, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            board.set_piece_at(move.from_square, piece)
            board.set_piece_at(move.to_square, chess.Piece(piece_type, cap_color))
            board.turn = not after.turn
            resolved = resolve_legal_uci_full(uci, board.fen())
            if not resolved:
                board.remove_piece_at(move.to_square)
                continue
            check = chess.Board(board.fen())
            check.push_uci(resolved)
            if check.board_fen() == after.board_fen() and check.turn == after.turn:
                return board
            board.remove_piece_at(move.to_square)
        return None

    board.turn = not after.turn
    return board


def fen_before_player_move(
    fen_after: str,
    uci: str,
    *,
    fen_before_hint: str | None = None,
) -> str | None:
    fen_after = (fen_after or '').strip()
    hint = (fen_before_hint or '').strip()
    if hint:
        resolved = resolve_legal_uci_full(uci, hint)
        if resolved:
            trial = chess.Board(hint)
            trial.push_uci(resolved)
            after = chess.Board(fen_after)
            if trial.fen() == fen_after or (
                trial.board_fen() == after.board_fen() and trial.turn == after.turn
            ):
                return hint

    after = chess.Board(fen_after)
    for cand_uci in _uci_promo_variants(uci):
        before = _undo_move_on_after_board(after, cand_uci)
        if before is None:
            continue
        fen_before = before.fen()
        resolved = resolve_legal_uci_full(cand_uci, fen_before)
        if resolved is None:
            continue
        check = chess.Board(fen_before)
        check.push_uci(resolved)
        if check.board_fen() == after.board_fen() and check.turn == after.turn:
            return fen_before
    return None


def test_fen_before_player_move_uses_hint():
    fen_before = 'rnbqkb1r/ppp2ppp/4pn2/1B1p4/3PP3/8/PPPN1PPP/R1BQK1NR b KQkq - 1 4'
    fen_after = 'rn1qkb1r/pppb1ppp/4pn2/1B1p4/3PP3/8/PPPN1PPP/R1BQK1NR w KQkq - 2 5'
    got = fen_before_player_move(fen_after, 'c8d7', fen_before_hint=fen_before)
    assert got == fen_before


def test_fen_before_player_move_infers_without_hint():
    fen_before = 'rnbqkb1r/ppp2ppp/4pn2/1B1p4/3PP3/8/PPPN1PPP/R1BQK1NR b KQkq - 1 4'
    fen_after = 'rn1qkb1r/pppb1ppp/4pn2/1B1p4/3PP3/8/PPPN1PPP/R1BQK1NR w KQkq - 2 5'
    got = fen_before_player_move(fen_after, 'c8d7')
    assert got is not None
    assert chess.Board(got).board_fen() == chess.Board(fen_before).board_fen()


def test_parse_auto_move_game_id_plain_uci():
    uci, fen_before = parse_auto_move_game_id('auto_move:e2e4')
    assert uci == 'e2e4'
    assert fen_before == ''


def test_parse_auto_move_game_id_with_fen_before():
    fen_before = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    game_id = f'auto_move:e2e4##{fen_before}'
    uci, parsed = parse_auto_move_game_id(game_id)
    assert uci == 'e2e4'
    assert parsed == fen_before


def test_scan_outcome_carries_fen_before():
    outcome = ScanOutcome(
        success=True,
        message='ok',
        fen='after',
        fen_before='before',
        uci='e2e4',
    )
    assert outcome.fen_before == 'before'
