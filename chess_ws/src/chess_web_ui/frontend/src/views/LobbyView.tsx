import { DIFFICULTY_LABELS, Difficulty, HumanColor } from '../chess';

const DIFFICULTY_INFO: Record<Difficulty, { title: string; desc: string; emoji: string }> = {
  easy: { title: '쉬움', desc: 'Elo ~900 · 천천히 두는 초보 봇', emoji: '🌱' },
  medium: { title: '보통', desc: 'Elo ~1500 · 아마추어 봇', emoji: '⚔️' },
  hard: { title: '어려움', desc: '풀 파워 · 마스터 봇', emoji: '🔥' },
};

type Props = {
  difficulty: Difficulty;
  humanColor: HumanColor;
  busy: boolean;
  onDifficulty: (d: Difficulty) => void;
  onColor: (c: HumanColor) => void;
  onStart: () => void;
};

export default function LobbyView({
  difficulty,
  humanColor,
  busy,
  onDifficulty,
  onColor,
  onStart,
}: Props) {
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

      <button type="button" className="start-btn" onClick={onStart} disabled={busy}>
        {busy ? '준비 중…' : `${DIFFICULTY_LABELS[difficulty]} 난이도 대결 시작`}
      </button>
    </div>
  );
}
