from chess_web_ui.voice_move_parser import VoiceMoveParseOk, parse_voice_command
from chess_web_ui.voice_stt_normalize import preprocess_transcript

START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def test_preprocess_spoken_file_and_rank() -> None:
    assert preprocess_transcript('에이 이 에이 삼') == 'a2 a3'


def test_preprocess_split_square() -> None:
    assert preprocess_transcript('e 2 e 4') in {'e2e4', 'e2 e4'}
    assert preprocess_transcript('a 2 a 3') in {'a2a3', 'a2 a3'}


def test_preprocess_spoken_c3_file() -> None:
    assert preprocess_transcript('씨 3') == 'c3'
    assert preprocess_transcript('씨3') == 'c3'


def test_parse_spoken_squares() -> None:
    result = parse_voice_command('에이 이 에이 삼', fen=START_FEN, human_color='white', llm_auto=False)
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'a2'
    assert result.move.to_sq == 'a3'


def test_parse_destination_only() -> None:
    result = parse_voice_command('e4로 가', fen=START_FEN, human_color='white', llm_auto=False)
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.to_sq == 'e4'
