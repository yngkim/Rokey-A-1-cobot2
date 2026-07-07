import { PIECE_PALETTE, PalettePiece, pieceImageUrl } from '../chess';

type Props = {
  selectedPiece: PalettePiece;
  whiteToMove: boolean;
  validationError: string | null;
  saveDisabled: boolean;
  busy: boolean;
  onSelectPiece: (piece: PalettePiece) => void;
  onToggleTurn: () => void;
  onSave: () => void;
  onCancel: () => void;
};

export default function BoardEditBar({
  selectedPiece,
  whiteToMove,
  validationError,
  saveDisabled,
  busy,
  onSelectPiece,
  onToggleTurn,
  onSave,
  onCancel,
}: Props) {
  return (
    <div className="board-edit-bar">
      <div className="board-edit-palette">
        {PIECE_PALETTE.map((item) => {
          const active = selectedPiece === item.piece;
          return (
            <button
              key={item.piece ?? 'erase'}
              type="button"
              className={`palette-btn${active ? ' palette-btn-active' : ''}`}
              title={item.label}
              onClick={() => onSelectPiece(item.piece)}
              disabled={busy}
            >
              {item.piece ? (
                <img src={pieceImageUrl(item.piece)} alt={item.label} draggable={false} />
              ) : (
                <span className="palette-erase">×</span>
              )}
            </button>
          );
        })}
      </div>
      <div className="board-edit-controls">
        <button type="button" className="action-btn action-btn-secondary" onClick={onToggleTurn} disabled={busy}>
          차례: {whiteToMove ? '백' : '흑'}
        </button>
        <button
          type="button"
          className="action-btn action-btn-primary"
          onClick={onSave}
          disabled={saveDisabled || busy}
        >
          {busy ? '저장 중…' : '저장'}
        </button>
        <button type="button" className="action-btn action-btn-secondary" onClick={onCancel} disabled={busy}>
          취소
        </button>
      </div>
      {validationError ? <p className="board-edit-error">{validationError}</p> : null}
    </div>
  );
}
