from chess_web_ui.voice_move_parser import (
    normalize_transcript,
    parse_voice_move,
    resolve_voice_move,
    VoiceMoveParseOk,
)


def test_normalize_korean_files() -> None:
    assert normalize_transcript('에이2 에이3') == 'a2 a3'


def test_parse_uci_compact() -> None:
    result = parse_voice_move('e2e4')
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'e2'
    assert result.move.to_sq == 'e4'


def test_parse_two_squares_with_piece_word() -> None:
    result = parse_voice_move('a2 폰 a3')
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'a2'
    assert result.move.to_sq == 'a3'


def test_parse_promotion_in_uci() -> None:
    result = parse_voice_move('a7a8q')
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.promotion == 'q'


def test_resolve_legal_move() -> None:
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    parsed = parse_voice_move('e2 e4')
    assert isinstance(parsed, VoiceMoveParseOk)
    uci, promo_required, _ = resolve_voice_move(fen, parsed.move)
    assert uci == 'e2e4'
    assert not promo_required


def test_resolve_illegal_move() -> None:
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    parsed = parse_voice_move('e2 e5')
    assert isinstance(parsed, VoiceMoveParseOk)
    uci, promo_required, msg = resolve_voice_move(fen, parsed.move)
    assert uci is None
    assert not promo_required
    assert msg == 'illegal move'
