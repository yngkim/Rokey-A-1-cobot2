export type BotSpeechKind =
  | 'greeting'
  | 'game_over'
  | 'check'
  | 'capture'
  | 'move'
  | 'illegal_move'
  | 'voice_move';
export type TtsMode = 'off' | 'important' | 'all';
export type TtsVoicePreset = 'male1' | 'male2' | 'female1' | 'female2';

export type UserSettings = {
  tts_enabled: boolean;
  tts_mode: TtsMode;
  tts_voice_preset: TtsVoicePreset;
  hand_auto_confirm_enabled: boolean;
};

const STORAGE_KEY = 'chess_user_settings';

const DEFAULT_SETTINGS: UserSettings = {
  tts_enabled: true,
  tts_mode: 'important',
  tts_voice_preset: 'female1',
  hand_auto_confirm_enabled: false,
};

const IMPORTANT_KINDS: ReadonlySet<BotSpeechKind> = new Set([
  'greeting',
  'game_over',
  'check',
  'capture',
  'illegal_move',
  'voice_move',
]);

export function shouldSpeak(kind: BotSpeechKind, settings: UserSettings): boolean {
  if (!settings.tts_enabled || settings.tts_mode === 'off') {
    return false;
  }
  if (settings.tts_mode === 'all') {
    return true;
  }
  return IMPORTANT_KINDS.has(kind);
}

export function loadUserSettings(): UserSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<UserSettings>;
    return {
      tts_enabled: parsed.tts_enabled ?? DEFAULT_SETTINGS.tts_enabled,
      tts_mode: parsed.tts_mode ?? DEFAULT_SETTINGS.tts_mode,
      tts_voice_preset: parsed.tts_voice_preset ?? DEFAULT_SETTINGS.tts_voice_preset,
      hand_auto_confirm_enabled:
        parsed.hand_auto_confirm_enabled ?? DEFAULT_SETTINGS.hand_auto_confirm_enabled,
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveUserSettings(settings: UserSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export const TTS_VOICE_LABELS: Record<TtsVoicePreset, string> = {
  male1: '남성 목소리 1',
  male2: '남성 목소리 2',
  female1: '여성 목소리 1',
  female2: '여성 목소리 2',
};

export const TTS_SAMPLE_TEXT = '안녕하세요, 체스 봇입니다.';
