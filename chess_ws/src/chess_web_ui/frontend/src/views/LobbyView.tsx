import { DIFFICULTY_LABELS, Difficulty, HumanColor } from '../chess';
import type { TtsMode, TtsVoicePreset, UserSettings } from '../lib/userSettings';
import {
  TTS_SAMPLE_TEXT,
  TTS_VOICE_LABELS,
  saveUserSettings,
} from '../lib/userSettings';
import { loadVoicePresets, speakText } from '../lib/ttsVoices';

const DIFFICULTY_INFO: Record<Difficulty, { title: string; desc: string; emoji: string }> = {
  easy: { title: '쉬움', desc: 'Elo ~900 · 천천히 두는 초보 봇', emoji: '🌱' },
  medium: { title: '보통', desc: 'Elo ~1500 · 아마추어 봇', emoji: '⚔️' },
  hard: { title: '어려움', desc: '풀 파워 · 마스터 봇', emoji: '🔥' },
};

const VOICE_PRESETS: TtsVoicePreset[] = ['male1', 'male2', 'female1', 'female2'];

type Props = {
  difficulty: Difficulty;
  humanColor: HumanColor;
  busy: boolean;
  userSettings: UserSettings;
  onDifficulty: (d: Difficulty) => void;
  onColor: (c: HumanColor) => void;
  onUserSettings: (settings: UserSettings) => void;
  onStart: () => void;
};

export default function LobbyView({
  difficulty,
  humanColor,
  busy,
  userSettings,
  onDifficulty,
  onColor,
  onUserSettings,
  onStart,
}: Props) {
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
      <h1>로봇 체스 대결</h1>
      <p className="lobby-sub">난이도와 색을 고른 뒤 실제 보드에서 대국을 시작하세요.</p>

      <div className="difficulty-grid">
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

      <button type="button" className="start-btn" onClick={onStart} disabled={busy}>
        {busy ? '준비 중…' : `${DIFFICULTY_LABELS[difficulty]} 난이도 대결 시작`}
      </button>
    </div>
  );
}
