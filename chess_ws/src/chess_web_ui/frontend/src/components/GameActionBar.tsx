type Props = {
  onConfirm: () => void;
  onReset: () => void;
  onRestore: () => void;
  onEdit: () => void;
  confirmDisabled: boolean;
  confirmBusy: boolean;
  resetDisabled: boolean;
  restoreDisabled: boolean;
  editDisabled: boolean;
  editing: boolean;
  restoreBusy: boolean;
};

export default function GameActionBar({
  onConfirm,
  onReset,
  onRestore,
  onEdit,
  confirmDisabled,
  confirmBusy,
  resetDisabled,
  restoreDisabled,
  editDisabled,
  editing,
  restoreBusy,
}: Props) {
  return (
    <div className="game-action-bar">
      <button
        type="button"
        className="action-btn action-btn-primary"
        onClick={onConfirm}
        disabled={confirmDisabled || confirmBusy || editing}
      >
        {confirmBusy ? '감지 중…' : '수 두었음'}
      </button>
      <button
        type="button"
        className="action-btn action-btn-secondary"
        onClick={onReset}
        disabled={resetDisabled || confirmBusy || editing}
      >
        Reset
      </button>
      <button
        type="button"
        className="action-btn action-btn-secondary"
        onClick={onRestore}
        disabled={restoreDisabled || confirmBusy || editing || restoreBusy}
      >
        {restoreBusy ? '정리 중…' : '보드 정리'}
      </button>
      <button
        type="button"
        className="action-btn action-btn-secondary"
        onClick={onEdit}
        disabled={editDisabled || confirmBusy || editing}
      >
        보드 수정
      </button>
    </div>
  );
}
