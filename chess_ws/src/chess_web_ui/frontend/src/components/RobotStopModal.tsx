type Props = {
  busy: boolean;
  onResume: () => void;
  onAbort: () => void;
};

export default function RobotStopModal({ busy, onResume, onAbort }: Props) {
  return (
    <div className="promotion-modal-backdrop" role="dialog" aria-modal="true">
      <div className="promotion-modal">
        <h3>로봇 동작 정지</h3>
        <p>로봇 팔 동작이 정지되었습니다. 계속할까요, 아니면 중단하고 홈으로 갈까요?</p>
        <div className="illegal-move-actions">
          <button
            type="button"
            className="action-btn action-btn-primary"
            disabled={busy}
            onClick={onResume}
          >
            계속하기
          </button>
          <button
            type="button"
            className="action-btn action-btn-danger"
            disabled={busy}
            onClick={onAbort}
          >
            중단하고 홈으로
          </button>
        </div>
      </div>
    </div>
  );
}
