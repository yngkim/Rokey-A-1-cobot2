import { pieceLabel } from '../chess';

type Props = {
  title: string;
  slots: (string | null)[];
  onChange: (slots: (string | null)[]) => void;
};

export default function GraveyardEditGrid({ title, slots, onChange }: Props) {
  const toggleSlot = (index: number) => {
    const next = [...slots];
    if (next[index]) {
      next[index] = null;
    } else {
      next[index] = 'p';
    }
    onChange(next);
  };

  return (
    <div className="graveyard-edit">
      <div className="graveyard-label">{title}</div>
      <div className="graveyard-pieces">
        {slots.map((piece, index) => (
          <button
            key={index}
            type="button"
            className={`graveyard-slot${piece ? ' occupied' : ''}`}
            onClick={() => toggleSlot(index)}
            title={`슬롯 ${index + 1}`}
          >
            {piece ? pieceLabel(piece) : '·'}
          </button>
        ))}
      </div>
    </div>
  );
}
