import { MoveRecord } from '../chess';

type Props = {
  moves: MoveRecord[];
  selectedPly: number | null;
  onSelect: (ply: number) => void;
};

export default function MoveList({ moves, selectedPly, onSelect }: Props) {
  const rows: { num: number; white?: MoveRecord; black?: MoveRecord }[] = [];
  for (let i = 0; i < moves.length; i += 2) {
    rows.push({
      num: Math.floor(i / 2) + 1,
      white: moves[i],
      black: moves[i + 1],
    });
  }

  if (rows.length === 0) {
    return <div className="move-list"><span style={{ color: '#9a9a9a' }}>수 기록 없음</span></div>;
  }

  return (
    <div className="move-list">
      {rows.map((row) => (
        <div className="move-row" key={row.num}>
          <span className="move-num">{row.num}.</span>
          <MoveCell move={row.white} selectedPly={selectedPly} onSelect={onSelect} />
          <MoveCell move={row.black} selectedPly={selectedPly} onSelect={onSelect} />
        </div>
      ))}
    </div>
  );
}

function MoveCell({
  move,
  selectedPly,
  onSelect,
}: {
  move?: MoveRecord;
  selectedPly: number | null;
  onSelect: (ply: number) => void;
}) {
  if (!move) return <span />;
  const selected = selectedPly === move.ply;
  return (
    <span
      className={['move-san', move.quality ?? ''].filter(Boolean).join(' ')}
      style={selected ? { background: 'rgba(129,182,76,0.25)', borderRadius: 4 } : undefined}
      onClick={() => onSelect(move.ply)}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(move.ply)}
      role="button"
      tabIndex={0}
    >
      {move.san}
    </span>
  );
}
