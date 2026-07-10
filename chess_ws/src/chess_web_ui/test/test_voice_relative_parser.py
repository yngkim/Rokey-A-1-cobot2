from chess_web_ui.voice_move_parser import VoiceMoveParseOk, parse_voice_command
from chess_web_ui.voice_relative_parser import parse_relative_voice_move

START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def test_relative_one_square_forward_white() -> None:
    result = parse_relative_voice_move('a2폰 한칸 앞', START_FEN, 'white')
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'a2'
    assert result.move.to_sq == 'a3'


def test_relative_two_squares_forward_white() -> None:
    result = parse_relative_voice_move('e2 폰 두칸 앞', START_FEN, 'white')
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'e2'
    assert result.move.to_sq == 'e4'


def test_relative_forward_black_human() -> None:
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1'
    result = parse_relative_voice_move('e7 한 칸 앞', fen, 'black')
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'e7'
    assert result.move.to_sq == 'e6'


def test_parse_voice_command_relative_fallback() -> None:
    result = parse_voice_command('a2폰 한칸 앞으로', fen=START_FEN, human_color='white', llm_auto=False)
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.to_sq == 'a3'


def test_relative_pawn_side_capture() -> None:
    fen = 'rnbqkbnr/pppp1ppp/8/4p3/3P4/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2'
    result = parse_voice_command('d4 폰 오른쪽 대각', fen=fen, human_color='white', llm_auto=False)
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'd4'
    assert result.move.to_sq == 'e5'
