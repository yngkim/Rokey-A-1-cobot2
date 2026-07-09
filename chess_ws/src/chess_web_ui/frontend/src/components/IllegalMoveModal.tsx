type Props = {
  fromSquare: string;
  toSquare: string;
  busy: boolean;
  onBoardEdit: () => void;
  onAutoRevert: () => void;
  onCancel: () => void;
};

export default function IllegalMoveModal({
  fromSquare,
  toSquare,
  busy,
  onBoardEdit,
  onAutoRevert,
  onCancel,
}: Props) {
  return (
    <div className="promotion-modal-backdrop" role="dialog" aria-modal="true">
      <div className="promotion-modal">
        <h3>불법 수 감지</h3>
        <p>
          {fromSquare} → {toSquare} 수는 체스 규칙에 맞지 않습니다.
        </p>
        <p>보드를 직접 수정하거나, 로봇이 기물을 원위치로 되돌리게 할 수 있습니다.</p>
        <div className="illegal-move-actions">
          <button
            type="button"
            className="action-btn action-btn-secondary"
            disabled={busy}
            onClick={onBoardEdit}
          >
            보드 수정
          </button>
          <button
            type="button"
            className="action-btn action-btn-primary"
            disabled={busy}
            onClick={onAutoRevert}
          >
            {busy ? '되돌리는 중…' : '자동 되돌리기'}
          </button>
        </div>
        <button type="button" className="promotion-cancel" disabled={busy} onClick={onCancel}>
          닫기
        </button>
      </div>
    </div>
  );
}
