type Props = {
  onConfirm: () => void;
  onReset: () => void;
  confirmDisabled: boolean;
  confirmBusy: boolean;
  resetDisabled: boolean;
};

export default function GameActionBar({
  onConfirm,
  onReset,
  confirmDisabled,
  confirmBusy,
  resetDisabled,
}: Props) {
  return (
    <div className="game-action-bar">
      <button
        type="button"
        className="action-btn action-btn-primary"
        onClick={onConfirm}
        disabled={confirmDisabled || confirmBusy}
      >
        {confirmBusy ? '감지 중…' : '수 두었음'}
      </button>
      <button
        type="button"
        className="action-btn action-btn-secondary"
        onClick={onReset}
        disabled={resetDisabled || confirmBusy}
      >
        Reset
      </button>
    </div>
  );
}
