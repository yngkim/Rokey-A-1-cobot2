"""StockfishClient must self-heal after a broken/corrupted engine subprocess.

Regression test for a bug where a single UCI protocol error (e.g. from two
threads talking to the same chess.engine.SimpleEngine concurrently — see
web_bridge.py's _with_engine locking around configure_opponent/choose_move)
left self._engine set to a dead handle forever. start() only creates a new
engine "if self._engine is None", so every choose_move() afterward silently
fell back to legal_moves[0].uci() for the rest of the process's life —
regardless of difficulty — which looks like the bot always developing the
same piece and shuffling a rook, never actually "thinking".
"""

from __future__ import annotations

import chess.engine
import pytest

from chess_engine.stockfish_client import StockfishClient

START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


@pytest.fixture
def client():
    c = StockfishClient(depth=4)
    yield c
    c.stop()


def test_choose_move_recovers_after_engine_error(client, monkeypatch) -> None:
    client.configure_opponent('medium')
    client.start()
    assert client._engine is not None

    def _boom(*_args, **_kwargs):
        raise chess.engine.EngineError('simulated UCI protocol corruption')

    monkeypatch.setattr(client._engine, 'play', _boom)

    # First call hits the broken engine, falls back, but must fully tear down
    # the dead handle rather than leaving it in place.
    uci = client.choose_move(START_FEN)
    assert uci  # fallback still returns a legal move
    assert client._engine is None
    assert client._engine_available is False

    # The NEXT call must spin up a fresh subprocess and actually think again,
    # not keep silently falling back forever.
    uci2 = client.choose_move(START_FEN)
    assert uci2
    assert client._engine is not None
    assert client._engine_available is True


def test_configure_opponent_resets_engine_on_failure(client, monkeypatch) -> None:
    client.start()
    live_engine = client._engine

    def _boom(*_args, **_kwargs):
        raise chess.engine.EngineError('simulated UCI protocol corruption')

    monkeypatch.setattr(live_engine, 'configure', _boom)
    client.configure_opponent('hard')

    assert client._engine is None
    assert client._engine_available is False

    # Recovers on next use.
    client.configure_opponent('hard')
    assert client._engine is not None
    assert client._engine_available is True
