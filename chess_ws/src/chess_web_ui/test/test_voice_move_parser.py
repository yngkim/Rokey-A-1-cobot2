from chess_web_ui.voice_move_parser import (
    normalize_transcript,
    parse_voice_command,
    parse_voice_command_with_meta,
    parse_voice_move,
    resolve_voice_move,
    looks_like_chess_move_command,
    VoiceMoveParseOk,
)

KNIGHT_CAPTURE_FEN = 'rnbqkbnr/pppp2pp/8/4p3/8/5N2/PPPP1PPP/RNBQKBNR w KQkq - 0 1'


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


def test_normalize_korean_natural_phrase() -> None:
    assert normalize_transcript('a2의 폰을 a3로 옮겨줘') == 'a2 a3'


def test_parse_voice_command_korean_natural() -> None:
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    result = parse_voice_command(
        'a2의 폰을 a3로 옮겨줘',
        fen=fen,
        human_color='white',
        llm_auto=False,
    )
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'a2'
    assert result.move.to_sq == 'a3'


def test_semantic_intent_skips_misleading_rule_squares() -> None:
    result, method = parse_voice_command_with_meta(
        'e2 e4 f3 나이트로 폰 잡아',
        fen=KNIGHT_CAPTURE_FEN,
        human_color='white',
        llm_auto=False,
    )
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'f3'
    assert result.move.to_sq == 'e5'
    assert method in ('semantic_strict', 'semantic_relaxed')


def test_capture_intent_blocks_llm_without_candidates() -> None:
    from chess_web_ui.voice_move_parser import VoiceMoveParseError

    result, method = parse_voice_command_with_meta(
        'h8 나이트로 폰 잡아',
        fen=KNIGHT_CAPTURE_FEN,
        human_color='white',
        llm_auto=False,
    )
    assert isinstance(result, VoiceMoveParseError)
    assert method == 'blocked_no_candidates'


def test_non_chess_phrase_does_not_trigger_move_parsing() -> None:
    from chess_web_ui.voice_move_parser import VoiceMoveParseError

    result, method = parse_voice_command_with_meta(
        '오늘 저녁 뭐 먹지',
        fen=KNIGHT_CAPTURE_FEN,
        human_color='white',
        llm_auto=True,
    )
    assert isinstance(result, VoiceMoveParseError)
    assert method == 'no_chess_intent'


def test_looks_like_chess_move_command_is_conservative() -> None:
    assert looks_like_chess_move_command('a2의 폰을 a3로 옮겨줘')
    assert looks_like_chess_move_command('나이트로 폰 잡아줘')
    assert not looks_like_chess_move_command('오늘 저녁 뭐 먹지')
