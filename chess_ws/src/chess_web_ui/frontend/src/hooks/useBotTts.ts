import { useEffect, useRef } from 'react';
import type { BoardResponse } from '../chess';
import type { BotSpeechKind, UserSettings } from '../lib/userSettings';
import { shouldSpeak } from '../lib/userSettings';
import { loadVoicePresets, speakText, stopSpeech } from '../lib/ttsVoices';

type Options = {
  enabled: boolean;
  settings: UserSettings;
  muted?: boolean;
};

export function useBotTts(board: BoardResponse | null, { enabled, settings, muted = false }: Options) {
  const lastSpokenRef = useRef('');
  const presetsRef = useRef<Awaited<ReturnType<typeof loadVoicePresets>> | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    loadVoicePresets().then((presets) => {
      if (!cancelled) presetsRef.current = presets;
    });
    return () => {
      cancelled = true;
      stopSpeech();
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled || muted || !board?.bot_message?.trim()) {
      return;
    }
    const kind = (board.bot_speech_kind ?? 'move') as BotSpeechKind;
    if (!shouldSpeak(kind, settings)) {
      return;
    }
    const key = `${kind}:${board.bot_message}`;
    if (lastSpokenRef.current === key) {
      return;
    }
    lastSpokenRef.current = key;

    const run = async () => {
      const presets = presetsRef.current ?? (await loadVoicePresets());
      presetsRef.current = presets;
      speakText(board.bot_message!, settings.tts_voice_preset, presets);
    };
    void run();
  }, [board?.bot_message, board?.bot_speech_kind, enabled, muted, settings]);
}
