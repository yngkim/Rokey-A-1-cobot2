import {
  GraveyardSide,
  PalettePiece,
  graveyardDisplayRows,
  graveyardSlotIndex,
  graveyardSlotLabel,
  pieceImageUrl,
} from '../chess';

type Props = {
  title: string;
  side: GraveyardSide;
  slots: (string | null)[];
  selectedPiece: PalettePiece;
  onChange: (slots: (string | null)[]) => void;
};

export default function GraveyardEditGrid({
  title,
  side,
  slots,
  selectedPiece,
  onChange,
}: Props) {
  const rows = graveyardDisplayRows(side);

  const handleSlotClick = (col: number, graveRow: number) => {
    const index = graveyardSlotIndex(col, graveRow);
    const next = [...slots];
    if (selectedPiece === null) {
      next[index] = null;
    } else {
      next[index] = selectedPiece;
    }
    onChange(next);
  };

  return (
    <div className="graveyard-edit">
      <div className="graveyard-label">{title}</div>
      <div className="graveyard-rows">
        {rows.map((rowSlots, rowIdx) => (
          <div className="graveyard-pieces" key={`gy-row-${rowIdx}`}>
            {rowSlots.map(([col, graveRow]) => {
              const index = graveyardSlotIndex(col, graveRow);
              const piece = slots[index];
              const label = graveyardSlotLabel(side, col, graveRow);
              const isWhite = piece ? piece === piece.toUpperCase() : false;
              return (
                <button
                  key={label}
                  type="button"
                  className={[
                    'graveyard-slot',
                    piece ? 'occupied' : '',
                    piece ? (isWhite ? 'piece-white' : 'piece-black') : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => handleSlotClick(col, graveRow)}
                  title={label}
                >
                  <span className="graveyard-slot-name">{label}</span>
                  {piece ? (
                    <img
                      className="graveyard-piece-img"
                      src={pieceImageUrl(piece)}
                      alt={piece}
                      draggable={false}
                    />
                  ) : null}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
