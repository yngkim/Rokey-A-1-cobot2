import { useCallback, useRef, useState } from 'react';

export type VoiceListenState = 'idle' | 'listening' | 'processing';

type BrowserSpeechRecognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((event: { resultIndex: number; results: SpeechRecognitionResultList }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionCtor = new () => BrowserSpeechRecognition;

function getSpeechRecognition(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') {
    return null;
  }
  const w = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useVoiceCommand() {
  const [state, setState] = useState<VoiceListenState>('idle');
  const [interimTranscript, setInterimTranscript] = useState('');
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);

  const startListening = useCallback(
    (durationMs = 5000): Promise<string> =>
      new Promise((resolve, reject) => {
        const Recognition = getSpeechRecognition();
        if (!Recognition) {
          reject(new Error('이 브라우저는 음성 인식을 지원하지 않습니다. Chrome 또는 Edge를 사용하세요.'));
          return;
        }

        const recognition = new Recognition();
        recognitionRef.current = recognition;
        recognition.lang = 'ko-KR';
        recognition.interimResults = true;
        recognition.continuous = true;
        recognition.maxAlternatives = 1;

        let finalText = '';
        let finished = false;

        const finish = (text: string) => {
          if (finished) return;
          finished = true;
          window.clearTimeout(timer);
          recognition.stop();
          setState('idle');
          setInterimTranscript('');
          recognitionRef.current = null;
          resolve(text.trim());
        };

        const fail = (message: string) => {
          if (finished) return;
          finished = true;
          window.clearTimeout(timer);
          recognition.stop();
          setState('idle');
          setInterimTranscript('');
          recognitionRef.current = null;
          reject(new Error(message));
        };

        recognition.onresult = (event) => {
          let interim = '';
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const part = event.results[i][0]?.transcript ?? '';
            if (event.results[i].isFinal) {
              finalText = `${finalText} ${part}`.trim();
            } else {
              interim = `${interim} ${part}`.trim();
            }
          }
          setInterimTranscript(finalText || interim ? `${finalText} ${interim}`.trim() : '');
        };

        recognition.onerror = (event) => {
          if (event.error === 'no-speech') {
            finish(finalText);
            return;
          }
          if (event.error === 'aborted') {
            finish(finalText);
            return;
          }
          fail(`음성 인식 오류: ${event.error}`);
        };

        recognition.onend = () => {
          if (!finished) {
            setState('processing');
            finish(finalText);
          }
        };

        setState('listening');
        setInterimTranscript('');
        finalText = '';

        try {
          recognition.start();
        } catch (err) {
          fail(err instanceof Error ? err.message : '음성 인식을 시작할 수 없습니다');
          return;
        }

        const timer = window.setTimeout(() => {
          setState('processing');
          recognition.stop();
        }, durationMs);
      }),
    [],
  );

  const cancelListening = useCallback(() => {
    recognitionRef.current?.stop();
    setState('idle');
    setInterimTranscript('');
  }, []);

  return {
    state,
    interimTranscript,
    startListening,
    cancelListening,
  };
}
