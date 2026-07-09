import { useCallback, useEffect, useState } from 'react';
import {
  BoardResponse,
  Difficulty,
  HumanColor,
  fetchBoard,
  postGameConfig,
  postPlayerMoved,
  postPlayerPromote,
  postBoardCorrect,
  postResign,
  postRevertIllegalMove,
  postUndo,
  postVoiceMove,
  resetBoard,
  restoreBoard,
} from './chess';
import { useBotTts } from './hooks/useBotTts';
import { useVoiceCommand } from './hooks/useVoiceCommand';
import { loadUserSettings, type UserSettings } from './lib/userSettings';
import LobbyView from './views/LobbyView';
import GameView from './views/GameView';
import PromotionModal from './components/PromotionModal';
import IllegalMoveModal from './components/IllegalMoveModal';
import './styles/chess-theme.css';

export default function App() {
  const [screen, setScreen] = useState<'lobby' | 'game'>('lobby');
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [humanColor, setHumanColor] = useState<HumanColor>('white');
  const [difficulty, setDifficulty] = useState<Difficulty>('medium');
  const [userSettings, setUserSettings] = useState<UserSettings>(() => loadUserSettings());
  const [ttsMuted, setTtsMuted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cameraTick, setCameraTick] = useState(0);
  const [error, setError] = useState('');
  const [pendingPromotion, setPendingPromotion] = useState<{ from: string; to: string } | null>(
    null,
  );
  const [pendingIllegalMove, setPendingIllegalMove] = useState<{ from: string; to: string } | null>(
    null,
  );
  const [boardEditRequest, setBoardEditRequest] = useState(0);
  const { state: voiceState, interimTranscript, startListening } = useVoiceCommand();
  const voiceListening = voiceState === 'listening' || voiceState === 'processing';

  useBotTts(board, {
    enabled: screen === 'game',
    settings: userSettings,
    muted: ttsMuted,
  });

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
    setError('');
    try {
      const data = await postPlayerMoved();
      setBoard(data);
      if (data.illegal_move && data.from && data.to) {
        setPendingIllegalMove({ from: data.from, to: data.to });
        setPendingPromotion(null);
      } else if (data.promotion_required && data.from && data.to) {
        setPendingPromotion({ from: data.from, to: data.to });
        setPendingIllegalMove(null);
      } else {
        setPendingPromotion(null);
        setPendingIllegalMove(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '수 감지 실패');
    } finally {
      setBusy(false);
    }
  };

  const handlePromotionPick = async (piece: 'q' | 'r' | 'b' | 'n') => {
    setBusy(true);
    setError('');
    try {
      const data = await postPlayerPromote(piece);
      setBoard(data);
      setPendingPromotion(null);
      if (!data.success && !data.promotion_required) {
        setError(data.message || '승격 처리 실패');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '승격 처리 실패');
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

  const handleRestore = async () => {
    setBusy(true);
    setError('');
    try {
      const data = await restoreBoard();
      setBoard(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '보드 정리 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleBackToLobby = () => {
    setScreen('lobby');
    setBoard(null);
    setTtsMuted(false);
    setError('');
  };

  const handleBoardCorrect = async (
    fen: string,
    graveyards?: {
      graveyard_slots?: (string | null)[];
      human_graveyard_slots?: (string | null)[];
    },
  ) => {
    setBusy(true);
    setError('');
    try {
      const data = await postBoardCorrect(fen, graveyards);
      setBoard(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '보드 정정 실패');
      throw err;
    } finally {
      setBusy(false);
    }
  };

  const handleResign = async () => {
    setBusy(true);
    setError('');
    try {
      const data = await postResign();
      setBoard(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '기권 처리 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async () => {
    setBusy(true);
    setError('');
    try {
      const data = await postUndo();
      setBoard(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Undo 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleIllegalAutoRevert = async () => {
    if (!pendingIllegalMove) return;
    setBusy(true);
    setError('');
    try {
      const data = await postRevertIllegalMove(
        pendingIllegalMove.from,
        pendingIllegalMove.to,
      );
      setBoard(data);
      setPendingIllegalMove(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '자동 되돌리기 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleIllegalBoardEdit = () => {
    setPendingIllegalMove(null);
    setBoardEditRequest((n) => n + 1);
  };

  const handleVoiceMove = async () => {
    setError('');
    try {
      const transcript = await startListening(5000);
      setBusy(true);
      const data = await postVoiceMove(transcript);
      setBoard(data);
      if (data.promotion_required && data.from && data.to) {
        setPendingPromotion({ from: data.from, to: data.to });
      }
      if (!data.success && !data.parse_error) {
        setError(data.message || '음성 명령 처리 실패');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '음성 명령 실패');
    } finally {
      setBusy(false);
    }
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
          userSettings={userSettings}
          onDifficulty={setDifficulty}
          onColor={setHumanColor}
          onUserSettings={setUserSettings}
          onStart={handleStart}
        />
      ) : board ? (
        <GameView
          board={board}
          humanColor={humanColor}
          cameraTick={cameraTick}
          busy={busy}
          ttsMuted={ttsMuted}
          onToggleTtsMute={() => setTtsMuted((v) => !v)}
          onConfirmMove={handleConfirmMove}
          onReset={handleReset}
          onRestore={handleRestore}
          onBackToLobby={handleBackToLobby}
          onResign={handleResign}
          onUndo={handleUndo}
          onVoiceMove={handleVoiceMove}
          voiceListening={voiceListening}
          voiceInterimText={interimTranscript}
          onBoardCorrect={handleBoardCorrect}
          boardEditRequest={boardEditRequest}
        />
      ) : (
        <p style={{ textAlign: 'center', color: '#9a9a9a' }}>로딩 중…</p>
      )}
      {pendingPromotion ? (
        <PromotionModal
          fromSquare={pendingPromotion.from}
          toSquare={pendingPromotion.to}
          humanColor={humanColor}
          busy={busy}
          onPick={handlePromotionPick}
          onCancel={() => setPendingPromotion(null)}
        />
      ) : null}
      {pendingIllegalMove ? (
        <IllegalMoveModal
          fromSquare={pendingIllegalMove.from}
          toSquare={pendingIllegalMove.to}
          busy={busy}
          onBoardEdit={handleIllegalBoardEdit}
          onAutoRevert={handleIllegalAutoRevert}
          onCancel={() => setPendingIllegalMove(null)}
        />
      ) : null}
    </div>
  );
}
