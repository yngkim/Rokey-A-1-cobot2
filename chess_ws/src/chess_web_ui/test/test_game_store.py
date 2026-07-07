import json
import tempfile
from pathlib import Path

from chess_web_ui.game_store import GameRecord, GameStore, START_FEN
from chess_web_ui.graveyard_utils import place_in_graveyard


def test_create_and_load_active_game():
    with tempfile.TemporaryDirectory() as tmp:
        store = GameStore(Path(tmp) / 'games.db')
        record = store.create_new_game(fen=START_FEN, human_color='white')
        record.fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'
        record.move_history = [{'ply': 1, 'uci': 'e2e4', 'san': 'e4'}]
        record.ply_counter = 1
        store.save_game(record)

        loaded = store.load_active_game()
        assert loaded is not None
        assert loaded.id == record.id
        assert loaded.fen == record.fen
        assert loaded.move_history[0]['uci'] == 'e2e4'


def test_graveyard_slots_roundtrip():
    slots = place_in_graveyard([None] * 16, 'black', 'p')
    with tempfile.TemporaryDirectory() as tmp:
        store = GameStore(Path(tmp) / 'games.db')
        record = store.create_new_game()
        record.graveyard_slots = slots
        store.save_game(record)
        loaded = store.load_active_game()
        assert loaded is not None
        assert 'p' in loaded.graveyard_slots


def test_human_graveyard_slots_roundtrip():
    slots = place_in_graveyard([None] * 16, 'white', 'n')
    with tempfile.TemporaryDirectory() as tmp:
        store = GameStore(Path(tmp) / 'games.db')
        record = store.create_new_game()
        record.human_graveyard_slots = slots
        store.save_game(record)
        loaded = store.load_active_game()
        assert loaded is not None
        assert 'n' in loaded.human_graveyard_slots
