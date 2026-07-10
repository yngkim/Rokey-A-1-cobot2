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

const CHESS_HINT_RE =
  /(?:[a-h]\s*[1-8]|에이|비|씨|디|이|에프|지|에이치|폰|말|나이트|비숍|룩|퀸|킹|앞|왼|오른|칸|e2|e4|a2|a3)/i;

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

function scoreTranscript(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  let score = trimmed.length;
  if (CHESS_HINT_RE.test(trimmed)) score += 20;
  if (/[a-h]\s*[1-8]/i.test(trimmed)) score += 15;
  if (/(?:앞|왼|오른|칸|폰|말)/.test(trimmed)) score += 10;
  return score;
}

function pickBestAlternative(result: SpeechRecognitionResult): string {
  let best = result[0]?.transcript ?? '';
  let bestScore = scoreTranscript(best);
  for (let i = 1; i < result.length; i += 1) {
    const candidate = result[i]?.transcript ?? '';
    const candidateScore = scoreTranscript(candidate);
    if (candidateScore > bestScore) {
      best = candidate;
      bestScore = candidateScore;
    }
  }
  return best;
}

export function useVoiceCommand() {
  const [state, setState] = useState<VoiceListenState>('idle');
  const [interimTranscript, setInterimTranscript] = useState('');
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);

  const startListening = useCallback(
    (durationMs = 7000): Promise<string> =>
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
        recognition.maxAlternatives = 5;

        let finalText = '';
        let latestInterim = '';
        let finished = false;

        const finish = (text: string) => {
          if (finished) return;
          finished = true;
          window.clearTimeout(timer);
          recognition.stop();
          setState('idle');
          setInterimTranscript('');
          recognitionRef.current = null;
          const resolved = (text || latestInterim).trim();
          resolve(resolved);
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
            const part = pickBestAlternative(event.results[i]);
            if (event.results[i].isFinal) {
              finalText = `${finalText} ${part}`.trim();
            } else {
              interim = `${interim} ${part}`.trim();
            }
          }
          latestInterim = interim;
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
        latestInterim = '';

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
