import { useCallback, useEffect, useState } from 'react';
import {
  BoardResponse,
  Difficulty,
  HumanColor,
  fetchBoard,
  postGameConfig,
  postPlayerMoved,
  resetBoard,
} from './chess';
import LobbyView from './views/LobbyView';
import GameView from './views/GameView';
import './styles/chess-theme.css';

export default function App() {
  const [screen, setScreen] = useState<'lobby' | 'game'>('lobby');
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [humanColor, setHumanColor] = useState<HumanColor>('white');
  const [difficulty, setDifficulty] = useState<Difficulty>('medium');
  const [busy, setBusy] = useState(false);
  const [cameraTick, setCameraTick] = useState(0);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const data = await fetchBoard();
      setBoard(data);
      if (data.human_color) setHumanColor(data.human_color);
      if (data.difficulty) setDifficulty(data.difficulty);
      if (data.game_phase === 'playing') setScreen('game');
    } catch (err) {
      setError(err instanceof Error ? err.message : '보드 로드 실패');
    }
  }, []);

  useEffect(() => {
    if (screen !== 'game') return undefined;
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, [refresh, screen]);

  useEffect(() => {
    if (screen !== 'game') return undefined;
    const timer = window.setInterval(() => setCameraTick(Date.now()), 400);
    return () => window.clearInterval(timer);
  }, [screen]);

  const handleStart = async () => {
    setBusy(true);
    setError('');
    try {
      await postGameConfig(humanColor, difficulty);
      const data = await resetBoard();
      setBoard(data);
      setScreen('game');
    } catch (err) {
      setError(err instanceof Error ? err.message : '게임 시작 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmMove = async () => {
    setBusy(true);
    try {
      const data = await postPlayerMoved();
      setBoard(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '수 감지 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async () => {
    setBusy(true);
    setError('');
    try {
      await postGameConfig(humanColor, difficulty);
      const data = await resetBoard();
      setBoard(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '리셋 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleBackToLobby = () => {
    setScreen('lobby');
    setBoard(null);
    setError('');
  };

  return (
    <div className="app-shell">
      {error ? (
        <p style={{ color: '#fa412d', textAlign: 'center', margin: '0 0 12px' }}>{error}</p>
      ) : null}
      {screen === 'lobby' ? (
        <LobbyView
          difficulty={difficulty}
          humanColor={humanColor}
          busy={busy}
          onDifficulty={setDifficulty}
          onColor={setHumanColor}
          onStart={handleStart}
        />
      ) : board ? (
        <GameView
          board={board}
          humanColor={humanColor}
          cameraTick={cameraTick}
          busy={busy}
          onConfirmMove={handleConfirmMove}
          onReset={handleReset}
          onBackToLobby={handleBackToLobby}
        />
      ) : (
        <p style={{ textAlign: 'center', color: '#9a9a9a' }}>로딩 중…</p>
      )}
    </div>
  );
}
