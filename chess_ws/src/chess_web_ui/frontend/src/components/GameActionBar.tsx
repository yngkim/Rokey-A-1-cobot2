type Props = {
  onConfirm: () => void;
  onReset: () => void;
  onRestore: () => void;
  onEdit: () => void;
  onResign: () => void;
  confirmDisabled: boolean;
  confirmBusy: boolean;
  resetDisabled: boolean;
  restoreDisabled: boolean;
  editDisabled: boolean;
  resignDisabled: boolean;
  editing: boolean;
  restoreBusy: boolean;
};

export default function GameActionBar({
  onConfirm,
  onReset,
  onRestore,
  onEdit,
  onResign,
  confirmDisabled,
  confirmBusy,
  resetDisabled,
  restoreDisabled,
  editDisabled,
  resignDisabled,
  editing,
  restoreBusy,
}: Props) {
  const handleResign = () => {
    if (!window.confirm('정말 기권하시겠습니까?')) return;
    onResign();
  };

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
      <button
        type="button"
        className="action-btn action-btn-danger"
        onClick={handleResign}
        disabled={resignDisabled || confirmBusy || editing}
      >
        기권
      </button>
    </div>
  );
}
