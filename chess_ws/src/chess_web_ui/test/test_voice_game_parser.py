from chess_web_ui.voice_game_parser import parse_game_voice_command


def test_parse_confirm_command() -> None:
    assert parse_game_voice_command('수 두었어') == 'confirm'
    assert parse_game_voice_command('확인') == 'confirm'
    assert parse_game_voice_command('움직였어') == 'confirm'


def test_parse_undo_command() -> None:
    assert parse_game_voice_command('한턴 전으로') == 'undo'
    assert parse_game_voice_command('되돌려') == 'undo'
    assert parse_game_voice_command('취소') == 'undo'


def test_parse_restore_command() -> None:
    assert parse_game_voice_command('보드 정리해줘') == 'restore'
    assert parse_game_voice_command('복구해줘') == 'restore'


def test_parse_resign_command() -> None:
    assert parse_game_voice_command('기권할게') == 'resign'
    assert parse_game_voice_command('포기') == 'resign'


def test_move_phrase_not_game_command() -> None:
    assert parse_game_voice_command('c3 나이트로 폰 잡아') is None
    assert parse_game_voice_command('e2 e4') is None
