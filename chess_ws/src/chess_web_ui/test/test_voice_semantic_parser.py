import chess

from chess_web_ui.voice_infer_parser import infer_destination_move
from chess_web_ui.voice_move_parser import VoiceMoveParseOk, parse_voice_command
from chess_web_ui.voice_semantic_parser import (
    extract_intent_slots,
    filter_moves_by_intent,
    has_semantic_intent,
    parse_semantic_voice_move,
)

# White knight f3, black pawn e5 — Nf3xe5 is the only knight pawn capture.
KNIGHT_CAPTURE_FEN = 'rnbqkbnr/pppp2pp/8/4p3/8/5N2/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
# White knight c3, black pawn d5 — Nc3xd5 is the only pawn capture from c3.
KNIGHT_C3_CAPTURE_FEN = 'rnbqkbnr/pppp2pp/8/3p4/8/2N5/PPPP1PPP/RNBQKBNR w KQkq - 0 1'


def test_extract_intent_slots_knight_capture() -> None:
    slots = extract_intent_slots('f3 나이트로 폰 잡아줘', KNIGHT_CAPTURE_FEN, 'white')
    assert slots.from_sq == 'f3'
    assert slots.piece == chess.KNIGHT
    assert slots.action == 'capture'
    assert slots.target_piece == chess.PAWN


def test_extract_intent_slots_compact_c3_capture() -> None:
    slots = extract_intent_slots('c3나이트로 폰 잡아줘', KNIGHT_C3_CAPTURE_FEN, 'white')
    assert slots.from_sq == 'c3'
    assert slots.piece == chess.KNIGHT
    assert slots.action == 'capture'
    assert slots.target_piece == chess.PAWN


def test_extract_intent_slots_stt_c3_spoken_file() -> None:
    slots = extract_intent_slots('씨3 나이트로 폰 잡아', KNIGHT_C3_CAPTURE_FEN, 'white')
    assert slots.from_sq == 'c3'
    assert slots.piece == chess.KNIGHT
    assert slots.target_piece == chess.PAWN


def test_filter_unique_knight_pawn_capture() -> None:
    slots = extract_intent_slots('f3 나이트로 폰 잡아줘')
    moves = filter_moves_by_intent(KNIGHT_CAPTURE_FEN, 'white', slots)
    assert len(moves) == 1
    assert moves[0].uci() == 'f3e5'


def test_parse_semantic_knight_capture() -> None:
    result = parse_semantic_voice_move(
        'f3 나이트로 폰 잡아줘',
        KNIGHT_CAPTURE_FEN,
        'white',
    )
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'f3'
    assert result.move.to_sq == 'e5'


def test_parse_semantic_compact_c3_capture() -> None:
    result = parse_semantic_voice_move(
        'c3나이트로 폰 잡아줘',
        KNIGHT_C3_CAPTURE_FEN,
        'white',
    )
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'c3'
    assert result.move.to_sq == 'd5'


def test_parse_semantic_relaxed_from_sq_capture() -> None:
    result = parse_semantic_voice_move(
        'c3에서 폰 잡아',
        KNIGHT_C3_CAPTURE_FEN,
        'white',
        relaxed=True,
    )
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'c3'
    assert result.move.to_sq == 'd5'


def test_parse_voice_command_semantic_capture() -> None:
    result = parse_voice_command(
        'f3 나이트로 폰 잡아줘',
        fen=KNIGHT_CAPTURE_FEN,
        human_color='white',
        llm_auto=False,
    )
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'f3'
    assert result.move.to_sq == 'e5'


def test_infer_skips_capture_destination() -> None:
    result = infer_destination_move(
        'f3 나이트로 폰 잡아줘',
        KNIGHT_CAPTURE_FEN,
        'white',
    )
    assert result.kind == 'parse_error'
    assert 'skipped' in result.message


def test_ambiguous_multiple_knight_pawn_captures() -> None:
    fen = '4k3/8/8/3pp3/8/2N2N2/8/4K3 w - - 0 1'
    slots = extract_intent_slots('나이트로 폰 잡아줘')
    moves = filter_moves_by_intent(fen, 'white', slots)
    assert len(moves) == 2
    result = parse_semantic_voice_move('나이트로 폰 잡아줘', fen, 'white')
    assert result.kind == 'ambiguous'


def test_ordinary_phrase_is_not_semantic_capture() -> None:
    assert not has_semantic_intent('오늘 저녁 뭐 먹지')
