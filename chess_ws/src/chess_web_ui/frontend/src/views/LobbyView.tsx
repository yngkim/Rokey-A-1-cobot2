import {
  BoardOrientation,
  DIFFICULTY_LABELS,
  Difficulty,
  HumanColor,
  SavedGameSummary,
  fetchSavedGames,
} from '../chess';
import type { TtsMode, TtsVoicePreset, UserSettings } from '../lib/userSettings';
import {
  TTS_SAMPLE_TEXT,
  TTS_VOICE_LABELS,
  saveUserSettings,
} from '../lib/userSettings';
import { loadVoicePresets, speakText } from '../lib/ttsVoices';
import { useEffect, useState } from 'react';

const DIFFICULTY_INFO: Record<Difficulty, { title: string; desc: string; emoji: string }> = {
  beginner: { title: '입문', desc: 'Elo ~700 · 천천히 두는 연습 봇', emoji: '🌱' },
  easy: { title: '쉬움', desc: 'Elo ~900 · 천천히 두는 초보 봇', emoji: '🙂' },
  medium: { title: '보통', desc: 'Elo ~1500 · 아마추어 봇', emoji: '⚔️' },
  hard: { title: '어려움', desc: 'Elo ~2000 · 고수 봇', emoji: '🔥' },
  master: { title: '마스터', desc: '풀 파워 · 마스터 봇', emoji: '👑' },
};

const VOICE_PRESETS: TtsVoicePreset[] = ['male1', 'male2', 'female1', 'female2'];

type Props = {
  difficulty: Difficulty;
  humanColor: HumanColor;
  boardOrientation: BoardOrientation;
  busy: boolean;
  userSettings: UserSettings;
  onDifficulty: (d: Difficulty) => void;
  onColor: (c: HumanColor) => void;
  onBoardOrientation: (o: BoardOrientation) => void;
  onUserSettings: (settings: UserSettings) => void;
  onStart: () => void;
  onResume: () => void;
  onLoadGame: (gameId: string) => void;
};

function formatSavedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function savedGameLabel(game: SavedGameSummary): string {
  const color = game.human_color === 'white' ? '백' : '흑';
  const diff = DIFFICULTY_LABELS[game.difficulty] ?? game.difficulty;
  const phase =
    game.game_phase === 'finished'
      ? '종료'
      : game.game_phase === 'playing'
        ? `${game.move_count}수`
        : '로비';
  return `${formatSavedAt(game.updated_at)} · ${diff} · ${color} · ${phase}`;
}

export default function LobbyView({
  difficulty,
  humanColor,
  boardOrientation,
  busy,
  userSettings,
  onDifficulty,
  onColor,
  onBoardOrientation,
  onUserSettings,
  onStart,
  onResume,
  onLoadGame,
}: Props) {
  const [savedGames, setSavedGames] = useState<SavedGameSummary[]>([]);
  const [savedGamesError, setSavedGamesError] = useState('');

  useEffect(() => {
    let cancelled = false;
    void fetchSavedGames()
      .then((games) => {
        if (!cancelled) setSavedGames(games);
      })
      .catch((err) => {
        if (!cancelled) {
          setSavedGamesError(err instanceof Error ? err.message : '저장 목록 로드 실패');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const resumeCandidate = savedGames.find(
    (game) => game.is_active && game.game_phase === 'playing',
  );
  const updateSettings = (patch: Partial<UserSettings>) => {
    const next = { ...userSettings, ...patch };
    saveUserSettings(next);
    onUserSettings(next);
  };

  const handleTtsEnabled = (enabled: boolean) => {
    updateSettings({ tts_enabled: enabled });
  };

  const handleTtsMode = (mode: TtsMode) => {
    updateSettings({ tts_enabled: true, tts_mode: mode });
  };

  const handleVoicePreview = async (preset: TtsVoicePreset) => {
    updateSettings({ tts_voice_preset: preset });
    const presets = await loadVoicePresets();
    speakText(TTS_SAMPLE_TEXT, preset, presets);
  };

  return (
    <div className="lobby">
      <div className="lobby-hero">
        <img src="/favicon.svg" alt="ChessMate" className="lobby-logo" />
        <div>
          <h1>ChessMate</h1>
          <p className="lobby-tagline">로봇 체스 대결</p>
        </div>
      </div>
      <p className="lobby-sub">난이도와 색을 고른 뒤 실제 보드에서 대국을 시작하세요.</p>

      <div className="difficulty-grid difficulty-grid-5">
        {(Object.keys(DIFFICULTY_INFO) as Difficulty[]).map((key) => {
          const info = DIFFICULTY_INFO[key];
          return (
            <button
              key={key}
              type="button"
              className={`difficulty-card ${difficulty === key ? 'selected' : ''}`}
              onClick={() => onDifficulty(key)}
              disabled={busy}
            >
              <div style={{ fontSize: '2rem' }}>{info.emoji}</div>
              <h3>{info.title}</h3>
              <p>{info.desc}</p>
            </button>
          );
        })}
      </div>

      <div className="color-row">
        <button
          type="button"
          className={`color-btn ${humanColor === 'white' ? 'selected' : ''}`}
          onClick={() => onColor('white')}
          disabled={busy}
        >
          ♔ 백 (선수)
        </button>
        <button
          type="button"
          className={`color-btn ${humanColor === 'black' ? 'selected' : ''}`}
          onClick={() => onColor('black')}
          disabled={busy}
        >
          ♚ 흑 (로봇 선수)
        </button>
      </div>

      <div className="color-row">
        <button
          type="button"
          className={`color-btn ${boardOrientation === 'standard' ? 'selected' : ''}`}
          onClick={() => onBoardOrientation('standard')}
          disabled={busy}
        >
          보드 표준 (a1 왼쪽 아래)
        </button>
        <button
          type="button"
          className={`color-btn ${boardOrientation === 'flipped' ? 'selected' : ''}`}
          onClick={() => onBoardOrientation('flipped')}
          disabled={busy}
        >
          보드 180° (a1 오른쪽 위)
        </button>
      </div>
      {boardOrientation === 'flipped' ? (
        <p className="lobby-sub lobby-hint">
          180° 배치 시 empty_board_depth.npz와 보드 코너를 다시 캘리브하세요.
        </p>
      ) : null}

      <section className="tts-settings">
        <h2>음성 설정</h2>
        <p className="tts-hint">OS에 한국어 TTS가 설치되어 있으면 음질이 좋아집니다.</p>

        <label className="tts-toggle">
          <input
            type="checkbox"
            checked={userSettings.tts_enabled}
            onChange={(e) => handleTtsEnabled(e.target.checked)}
            disabled={busy}
          />
          <span>봇 대사 음성 켜기</span>
        </label>

        <div className={`tts-mode-row${userSettings.tts_enabled ? '' : ' disabled'}`}>
          <label>
            <input
              type="radio"
              name="tts_mode"
              checked={userSettings.tts_mode === 'important'}
              onChange={() => handleTtsMode('important')}
              disabled={busy || !userSettings.tts_enabled}
            />
            중요한 대사만 (체크·체크메이트·포획·인사)
          </label>
          <label>
            <input
              type="radio"
              name="tts_mode"
              checked={userSettings.tts_mode === 'all'}
              onChange={() => handleTtsMode('all')}
              disabled={busy || !userSettings.tts_enabled}
            />
            매 수마다
          </label>
        </div>

        <div className="tts-voice-grid">
          {VOICE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={`tts-voice-btn${userSettings.tts_voice_preset === preset ? ' selected' : ''}`}
              onClick={() => void handleVoicePreview(preset)}
              disabled={busy}
            >
              {TTS_VOICE_LABELS[preset]}
            </button>
          ))}
        </div>
      </section>

      <section className="tts-settings">
        <h2>손 감지</h2>
        <p className="tts-hint">
          사이드뷰 검증이 켜져 있을 때 동작합니다. 손이 보드에서 사라지면 RealSense로 수를 자동 확인합니다.
        </p>
        <label className="tts-toggle">
          <input
            type="checkbox"
            checked={userSettings.hand_auto_confirm_enabled}
            onChange={(e) => updateSettings({ hand_auto_confirm_enabled: e.target.checked })}
            disabled={busy}
          />
          <span>손 감지 자동 수 확인 (기본 OFF)</span>
        </label>
      </section>

      <section className="saved-games-section">
        <h2>저장된 게임</h2>
        <p className="lobby-sub lobby-hint">
          진행 중인 게임은 자동 저장됩니다. 재시작 후 「이어하기」로 복원할 수 있습니다.
        </p>
        {resumeCandidate ? (
          <button
            type="button"
            className="resume-btn"
            onClick={onResume}
            disabled={busy}
          >
            이어하기 ({savedGameLabel(resumeCandidate)})
          </button>
        ) : null}
        {savedGamesError ? <p className="saved-games-error">{savedGamesError}</p> : null}
        {savedGames.length > 0 ? (
          <ul className="saved-games-list">
            {savedGames.map((game) => (
              <li key={game.id} className={game.is_active ? 'saved-game-active' : ''}>
                <div className="saved-game-meta">
                  <strong>{savedGameLabel(game)}</strong>
                  <span className="saved-game-id">{game.id.slice(0, 8)}</span>
                </div>
                <button
                  type="button"
                  className="saved-game-load-btn"
                  onClick={() => onLoadGame(game.id)}
                  disabled={busy}
                >
                  불러오기
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="lobby-sub">저장된 게임이 없습니다.</p>
        )}
      </section>

      <button type="button" className="start-btn" onClick={onStart} disabled={busy}>
        {busy ? '준비 중…' : `${DIFFICULTY_LABELS[difficulty]} 난이도 대결 시작`}
      </button>
    </div>
  );
}
