from chess_web_ui.voice_infer_parser import infer_destination_move, infer_voice_move
from chess_web_ui.voice_move_parser import VoiceMoveParseOk

START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def test_infer_unique_destination() -> None:
    result = infer_destination_move('e4', START_FEN, 'white')
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.to_sq == 'e4'
    assert result.move.from_sq == 'e2'


def test_infer_messy_square_pair() -> None:
    result = infer_voice_move('a2의 폰 a3', START_FEN, 'white')
    assert isinstance(result, VoiceMoveParseOk)
    assert result.move.from_sq == 'a2'
    assert result.move.to_sq == 'a3'
