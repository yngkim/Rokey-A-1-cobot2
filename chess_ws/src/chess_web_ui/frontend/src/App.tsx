import { useCallback, useEffect, useState } from 'react';
import {
  BoardResponse,
  BoardOrientation,
  Difficulty,
  HumanColor,
  fetchBoard,
  postGameConfig,
  postPlayerMoved,
  postPlayerPromote,
  postBoardCorrect,
  postResign,
  postRevertIllegalMove,
  postTwinVerify,
  postTwinConfig,
  postHandConfig,
  postHandSafetyConfig,
  postUndo,
  postVoiceMove,
  postResumeGame,
  postSaveGame,
  postLoadGame,
  resetBoard,
  restoreBoard,
  stopRobot,
  resumeRobot,
  abortRobot,
} from './chess';
import { useBotTts } from './hooks/useBotTts';
import { useVoiceCommand } from './hooks/useVoiceCommand';
import { loadUserSettings, saveUserSettings, type UserSettings } from './lib/userSettings';
import LobbyView from './views/LobbyView';
import GameView from './views/GameView';
import PromotionModal from './components/PromotionModal';
import IllegalMoveModal from './components/IllegalMoveModal';
import RobotStopModal from './components/RobotStopModal';
import './styles/chess-theme.css';

export default function App() {
  const [screen, setScreen] = useState<'lobby' | 'game'>('lobby');
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [humanColor, setHumanColor] = useState<HumanColor>('white');
  const [difficulty, setDifficulty] = useState<Difficulty>('medium');
  const [boardOrientation, setBoardOrientation] = useState<BoardOrientation>('standard');
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
  const [saveBusy, setSaveBusy] = useState(false);
  const [showStopModal, setShowStopModal] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
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
      if (data.board_orientation) setBoardOrientation(data.board_orientation);
      if (data.game_phase === 'playing' || data.game_phase === 'finished') {
        setScreen('game');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '보드 로드 실패');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (screen !== 'game') return undefined;
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, [refresh, screen]);

  useEffect(() => {
    if (screen !== 'game') return undefined;
    const timer = window.setInterval(() => setCameraTick(Date.now()), 100);
    return () => window.clearInterval(timer);
  }, [screen]);

  useEffect(() => {
    if (board?.user_stop_pending) {
      setShowStopModal(true);
    }
  }, [board?.user_stop_pending]);

  const applyBoardState = (data: BoardResponse) => {
    setBoard(data);
    if (data.human_color) setHumanColor(data.human_color);
    if (data.difficulty) setDifficulty(data.difficulty);
    if (data.board_orientation) setBoardOrientation(data.board_orientation);
    if (data.game_phase === 'playing' || data.game_phase === 'finished') {
      setScreen('game');
    }
  };

  const handleResume = async () => {
    setBusy(true);
    setError('');
    try {
      const data = await postResumeGame();
      applyBoardState(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '게임 이어하기 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleLoadGame = async (gameId: string) => {
    if (
      !window.confirm(
        '선택한 게임을 불러옵니다. 논리 보드와 로봇이 저장 시점 상태로 맞춰집니다. 계속할까요?',
      )
    ) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      const data = await postLoadGame(gameId);
      applyBoardState(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '게임 불러오기 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleSaveGame = async () => {
    setSaveBusy(true);
    setError('');
    try {
      const data = await postSaveGame();
      setBoard(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '게임 저장 실패');
    } finally {
      setSaveBusy(false);
    }
  };

  const handleStart = async () => {
    setBusy(true);
    setError('');
    try {
      await postGameConfig(
        humanColor,
        difficulty,
        boardOrientation,
        userSettings.hand_auto_confirm_enabled,
      );
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
      await postGameConfig(humanColor, difficulty, boardOrientation);
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

  const handleTwinToggle = async (enabled: boolean) => {
    setBusy(true);
    setError('');
    try {
      const data = await postTwinConfig(enabled);
      setBoard(data);
      setCameraTick(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err.message : '사이드뷰 검증 설정 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleHandAutoConfirmToggle = async (enabled: boolean) => {
    setBusy(true);
    setError('');
    try {
      const data = await postHandConfig(enabled);
      setBoard(data);
      setUserSettings((prev) => {
        const next = { ...prev, hand_auto_confirm_enabled: enabled };
        saveUserSettings(next);
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '손 감지 설정 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleHandSafetyToggle = async (enabled: boolean) => {
    setBusy(true);
    setError('');
    try {
      const data = await postHandSafetyConfig(enabled);
      setBoard(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '손 감지 안전정지 설정 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleTwinVerify = async () => {
    setBusy(true);
    setError('');
    try {
      const data = await postTwinVerify({ use_fresh_scan: true });
      setBoard(data);
      if (!data.twin_report?.aligned) {
        setError(data.twin_report?.message || '보드 불일치가 감지되었습니다');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '보드 검증 실패');
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
      const transcript = await startListening(7000);
      setBusy(true);
      const data = await postVoiceMove(transcript);
      setBoard(data);
      if (data.promotion_required && data.from && data.to) {
        setPendingPromotion({ from: data.from, to: data.to });
      }
      if (data.voice_action && data.voice_action !== 'move' && data.voice_action !== 'parse_error') {
        if (!data.success) {
          setError(data.message || '음성 게임 명령 처리 실패');
        }
        return;
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

  const handleRobotStop = async () => {
    setStopBusy(true);
    setError('');
    try {
      const data = await stopRobot();
      setBoard(data);
      setShowStopModal(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : '로봇 정지 실패');
    } finally {
      setStopBusy(false);
    }
  };

  const handleRobotResume = async () => {
    setStopBusy(true);
    setError('');
    try {
      const data = await resumeRobot();
      setBoard(data);
      setShowStopModal(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '로봇 재개 실패');
    } finally {
      setStopBusy(false);
    }
  };

  const handleRobotAbort = async () => {
    setStopBusy(true);
    setError('');
    try {
      const data = await abortRobot();
      setBoard(data);
      setShowStopModal(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '로봇 중단 실패');
    } finally {
      setStopBusy(false);
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
          boardOrientation={boardOrientation}
          busy={busy}
          userSettings={userSettings}
          onDifficulty={setDifficulty}
          onColor={setHumanColor}
          onBoardOrientation={setBoardOrientation}
          onUserSettings={setUserSettings}
          onStart={handleStart}
          onResume={handleResume}
          onLoadGame={handleLoadGame}
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
          onSave={handleSaveGame}
          saveBusy={saveBusy}
          onBackToLobby={handleBackToLobby}
          onResign={handleResign}
          onUndo={handleUndo}
          onVoiceMove={handleVoiceMove}
          onRobotStop={handleRobotStop}
          stopBusy={stopBusy}
          onTwinVerify={handleTwinVerify}
          onTwinToggle={handleTwinToggle}
          onHandAutoConfirmToggle={handleHandAutoConfirmToggle}
          onHandSafetyToggle={handleHandSafetyToggle}
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
      {showStopModal ? (
        <RobotStopModal
          busy={stopBusy || busy}
          onResume={handleRobotResume}
          onAbort={handleRobotAbort}
        />
      ) : null}
    </div>
  );
}
