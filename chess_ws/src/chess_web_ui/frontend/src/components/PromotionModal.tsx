type PromotionPiece = 'q' | 'r' | 'b' | 'n';

type Props = {
  fromSquare: string;
  toSquare: string;
  humanColor: 'white' | 'black';
  busy: boolean;
  onPick: (piece: PromotionPiece) => void;
  onCancel: () => void;
};

const OPTIONS: { id: PromotionPiece; white: string; black: string; label: string }[] = [
  { id: 'q', white: '♕', black: '♛', label: '퀸' },
  { id: 'r', white: '♖', black: '♜', label: '룩' },
  { id: 'b', white: '♗', black: '♝', label: '비숍' },
  { id: 'n', white: '♘', black: '♞', label: '나이트' },
];

export default function PromotionModal({
  fromSquare,
  toSquare,
  humanColor,
  busy,
  onPick,
  onCancel,
}: Props) {
  return (
    <div className="promotion-modal-backdrop" role="dialog" aria-modal="true">
      <div className="promotion-modal">
        <h3>승격 기물 선택</h3>
        <p>
          {fromSquare} → {toSquare}
        </p>
        <div className="promotion-options">
          {OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className="promotion-option"
              disabled={busy}
              onClick={() => onPick(opt.id)}
            >
              <span className="promotion-piece">
                {humanColor === 'white' ? opt.white : opt.black}
              </span>
              <span>{opt.label}</span>
            </button>
          ))}
        </div>
        <button type="button" className="promotion-cancel" disabled={busy} onClick={onCancel}>
          취소
        </button>
      </div>
    </div>
  );
}
