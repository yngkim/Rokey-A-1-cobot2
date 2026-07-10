from chess_web_ui.voice_llm_parser import build_voice_llm_prompt, parse_voice_move_llm
from chess_web_ui.voice_move_parser import VoiceMoveParseOk
from chess_web_ui.voice_semantic_parser import extract_intent_slots, filter_moves_by_intent

START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
KNIGHT_CAPTURE_FEN = 'rnbqkbnr/pppp2pp/8/4p3/8/5N2/PPPP1PPP/RNBQKBNR w KQkq - 0 1'


def test_build_voice_llm_prompt_includes_fen_and_transcript() -> None:
    prompt = build_voice_llm_prompt('a2의 폰을 a3로', START_FEN, 'white')
    assert START_FEN in prompt
    assert 'a2의 폰을 a3로' in prompt
    assert 'Human pieces:' in prompt
    assert 'e2' in prompt


def test_build_voice_llm_prompt_includes_capture_annotation() -> None:
    slots = extract_intent_slots('f3 나이트로 폰 잡아줘')
    candidates = filter_moves_by_intent(KNIGHT_CAPTURE_FEN, 'white', slots)
    prompt = build_voice_llm_prompt(
        'f3 나이트로 폰 잡아줘',
        KNIGHT_CAPTURE_FEN,
        'white',
        slots=slots,
        candidate_moves=candidates,
    )
    assert 'captures pawn' in prompt
    assert 'Parsed intent:' in prompt
    assert 'f3e5' in prompt


def test_parse_voice_move_llm_success() -> None:
    def fake_generate(prompt: str, *, model: str, base_url: str, timeout_sec: float) -> str:
        assert 'a2' in prompt
        return '{"from":"a2","to":"a3","promotion":""}'

    result = parse_voice_move_llm(
        'a2 pawn to a3',
        START_FEN,
        'white',
        generate_fn=fake_generate,
    )
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'a2'
    assert result.move.to_sq == 'a3'


def test_parse_voice_move_llm_rejects_illegal_move() -> None:
    def fake_generate(prompt: str, *, model: str, base_url: str, timeout_sec: float) -> str:
        return '{"from":"e2","to":"e5","promotion":""}'

    result = parse_voice_move_llm(
        'e2 to e5',
        START_FEN,
        'white',
        generate_fn=fake_generate,
    )
    assert result.kind == 'parse_error'
    assert 'not legal' in result.message


def test_parse_voice_move_llm_skips_call_for_unique_candidate() -> None:
    called = False

    def fake_generate(prompt: str, *, model: str, base_url: str, timeout_sec: float) -> str:
        nonlocal called
        called = True
        return '{"from":"f3","to":"e5","promotion":""}'

    result = parse_voice_move_llm(
        'f3 나이트로 폰 잡아줘',
        KNIGHT_CAPTURE_FEN,
        'white',
        generate_fn=fake_generate,
    )
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'f3'
    assert result.move.to_sq == 'e5'
    assert not called


def test_parse_voice_move_llm_invalid_json() -> None:
    def fake_generate(prompt: str, *, model: str, base_url: str, timeout_sec: float) -> str:
        return 'not json'

    result = parse_voice_move_llm(
        'move pawn',
        START_FEN,
        'white',
        generate_fn=fake_generate,
    )
    assert result.kind == 'parse_error'
    assert 'invalid JSON' in result.message


def test_parse_voice_move_llm_blocked_without_candidates() -> None:
    called = False

    def fake_generate(prompt: str, *, model: str, base_url: str, timeout_sec: float) -> str:
        nonlocal called
        called = True
        return '{"from":"f3","to":"e5","promotion":""}'

    result = parse_voice_move_llm(
        'h8 나이트로 폰 잡아',
        KNIGHT_CAPTURE_FEN,
        'white',
        candidate_moves=[],
        allow_full_legal_list=False,
        generate_fn=fake_generate,
    )
    assert result.kind == 'parse_error'
    assert 'blocked' in result.message
    assert not called
