import { pieceImageUrl } from '../chess';

type Props = {
  pieces: string[];
};

export default function CapturedBar({ pieces }: Props) {
  const filtered = pieces.filter((p) => p);
  if (filtered.length === 0) return <div className="captured-bar" />;
  return (
    <div className="captured-bar">
      {filtered.map((p, i) => (
        <img key={`${p}-${i}`} src={pieceImageUrl(p)} alt={p} />
      ))}
    </div>
  );
}
