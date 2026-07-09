import type { TtsVoicePreset } from './userSettings';

export type VoicePresetConfig = {
  pitch: number;
  voice: SpeechSynthesisVoice | null;
};

const FEMALE_HINTS = ['female', 'woman', 'girl', 'yuna', 'heami', 'sora', 'nara', 'female'];
const MALE_HINTS = ['male', 'man', 'boy', 'hyuntaek', 'injoon'];

function isKoreanVoice(voice: SpeechSynthesisVoice): boolean {
  return voice.lang.toLowerCase().startsWith('ko');
}

function voiceGenderScore(voice: SpeechSynthesisVoice, female: boolean): number {
  const name = voice.name.toLowerCase();
  const hints = female ? FEMALE_HINTS : MALE_HINTS;
  const opposite = female ? MALE_HINTS : FEMALE_HINTS;
  let score = 0;
  for (const hint of hints) {
    if (name.includes(hint)) score += 2;
  }
  for (const hint of opposite) {
    if (name.includes(hint)) score -= 2;
  }
  return score;
}

function pickVoices(voices: SpeechSynthesisVoice[]): {
  korean: SpeechSynthesisVoice[];
  fallback: SpeechSynthesisVoice[];
} {
  const korean = voices.filter(isKoreanVoice);
  const fallback = voices.length ? voices : [];
  return { korean, fallback };
}

function bestVoice(
  pool: SpeechSynthesisVoice[],
  female: boolean,
  used: Set<string>,
): SpeechSynthesisVoice | null {
  const ranked = [...pool].sort((a, b) => voiceGenderScore(b, female) - voiceGenderScore(a, female));
  for (const voice of ranked) {
    if (!used.has(voice.voiceURI)) {
      return voice;
    }
  }
  return ranked[0] ?? null;
}

export function buildVoicePresets(voices: SpeechSynthesisVoice[]): Record<TtsVoicePreset, VoicePresetConfig> {
  const { korean, fallback } = pickVoices(voices);
  const pool = korean.length > 0 ? korean : fallback;
  const used = new Set<string>();

  const male1Voice = bestVoice(pool, false, used);
  if (male1Voice) used.add(male1Voice.voiceURI);
  const male2Voice = bestVoice(pool, false, used) ?? male1Voice;
  if (male2Voice) used.add(male2Voice.voiceURI);
  const female1Voice = bestVoice(pool, true, used) ?? pool[0] ?? null;
  if (female1Voice) used.add(female1Voice.voiceURI);
  const female2Voice = bestVoice(pool, true, used) ?? female1Voice;

  return {
    male1: { voice: male1Voice, pitch: 0.85 },
    male2: { voice: male2Voice ?? male1Voice, pitch: 0.95 },
    female1: { voice: female1Voice, pitch: 1.05 },
    female2: { voice: female2Voice ?? female1Voice, pitch: 1.15 },
  };
}

let cachedPresets: Record<TtsVoicePreset, VoicePresetConfig> | null = null;

export function loadVoicePresets(): Promise<Record<TtsVoicePreset, VoicePresetConfig>> {
  if (cachedPresets) {
    return Promise.resolve(cachedPresets);
  }
  if (typeof window === 'undefined' || !window.speechSynthesis) {
    return Promise.resolve(buildVoicePresets([]));
  }

  return new Promise((resolve) => {
    const finish = () => {
      cachedPresets = buildVoicePresets(window.speechSynthesis.getVoices());
      resolve(cachedPresets);
    };
    const voices = window.speechSynthesis.getVoices();
    if (voices.length > 0) {
      finish();
      return;
    }
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis.onvoiceschanged = null;
      finish();
    };
    window.setTimeout(finish, 500);
  });
}

export function speakText(
  text: string,
  preset: TtsVoicePreset,
  presets: Record<TtsVoicePreset, VoicePresetConfig>,
): void {
  if (!text.trim() || typeof window === 'undefined' || !window.speechSynthesis) {
    return;
  }
  const config = presets[preset];
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'ko-KR';
  utterance.rate = 1.0;
  utterance.pitch = config.pitch;
  if (config.voice) {
    utterance.voice = config.voice;
  }
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

export function stopSpeech(): void {
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
}
