import type { TwinReport } from '../chess';

type Props = {
  report: TwinReport | null | undefined;
  runtimeEnabled: boolean;
  available: boolean;
  handAutoConfirmEnabled?: boolean;
  handSafetyEnabled?: boolean;
  handAvailable?: boolean;
  busy: boolean;
  onVerify: () => void;
  onToggleRuntime: (enabled: boolean) => void;
  onToggleHandAutoConfirm?: (enabled: boolean) => void;
  onToggleHandSafety?: (enabled: boolean) => void;
  onApplyCandidate?: (fen: string) => void;
};

export default function TwinPanel({
  report,
  runtimeEnabled,
  available,
  handAutoConfirmEnabled = false,
  handSafetyEnabled = true,
  handAvailable = false,
  busy,
  onVerify,
  onToggleRuntime,
  onToggleHandAutoConfirm,
  onToggleHandSafety,
  onApplyCandidate,
}: Props) {
  const candidate = report?.suggestions?.find(
    (item) => item.kind === 'correct_board_candidate_fen' && item.candidate_fen,
  );

  return (
    <section className="twin-panel">
      <div className="twin-panel-header">
        <h3>Reality Check</h3>
        {available ? (
          <label className="twin-toggle">
            <input
              type="checkbox"
              checked={runtimeEnabled}
              disabled={busy}
              onChange={(e) => onToggleRuntime(e.target.checked)}
            />
            <span>사이드뷰 검증</span>
          </label>
        ) : null}
      </div>
      {!available ? (
        <p className="twin-panel-empty">이 launch에서는 사이드뷰 검증을 사용할 수 없습니다.</p>
      ) : !runtimeEnabled ? (
        <p className="twin-panel-empty">
          사이드뷰 보드 검증이 꺼져 있습니다. 토글을 켜면 웹캠 인식과 기록 보드 비교가 시작됩니다.
        </p>
      ) : !report ? (
        <p className="twin-panel-empty">
          기록 보드와 사이드뷰 인식을 참고용으로 비교합니다. RealSense 수 확인 흐름은 그대로입니다.
        </p>
      ) : (
        <>
          <p className={`twin-panel-status${report.aligned ? ' twin-ok' : ' twin-warn'}`}>{report.message}</p>
          {report.mismatches?.length ? (
            <ul className="twin-mismatch-list">
              {report.mismatches.slice(0, 6).map((item) => (
                <li key={`${item.kind}-${item.square}-${item.message}`}>
                  <strong>{item.square || 'board'}</strong> {item.message}
                </li>
              ))}
            </ul>
          ) : null}
          {report.suggestions?.length ? (
            <ul className="twin-suggestion-list">
              {report.suggestions.slice(0, 4).map((item) => (
                <li key={`${item.kind}-${item.message}`}>{item.message}</li>
              ))}
            </ul>
          ) : null}
          {candidate?.candidate_fen && onApplyCandidate ? (
            <button
              type="button"
              className="action-btn action-btn-secondary"
              onClick={() => onApplyCandidate(candidate.candidate_fen!)}
              disabled={busy}
            >
              추천 FEN 보드 수정 열기 (참고용)
            </button>
          ) : null}
        </>
      )}
      {handAvailable ? (
        <label className="twin-toggle twin-hand-toggle">
          <input
            type="checkbox"
            checked={handAutoConfirmEnabled}
            disabled={busy}
            onChange={(e) => onToggleHandAutoConfirm?.(e.target.checked)}
          />
          <span>손 감지 자동 수 확인</span>
        </label>
      ) : null}
      {handAvailable ? (
        <label className="twin-toggle twin-hand-toggle">
          <input
            type="checkbox"
            checked={handSafetyEnabled}
            disabled={busy}
            onChange={(e) => onToggleHandSafety?.(e.target.checked)}
          />
          <span>손 감지 시 로봇 정지</span>
        </label>
      ) : null}
      {handAvailable && !handSafetyEnabled ? (
        <p className="twin-hand-hint twin-hand-warn">
          꺼짐 — 손이 보드 위에 있어도 로봇이 멈추지 않습니다. 오탐이 잦을 때만 끄고,
          실제로 손을 보드에 넣을 땐 직접 정지 버튼을 쓰세요.
        </p>
      ) : null}
      {handAvailable ? (
        <p className="twin-hand-hint">
          손이 보드에서 사라지면 RealSense로 수를 확인한 뒤 로봇이 응수합니다.
        </p>
      ) : null}
      {available && runtimeEnabled ? (
        <button
          type="button"
          className="action-btn action-btn-secondary twin-verify-btn"
          onClick={onVerify}
          disabled={busy}
        >
          {busy ? '검증 중…' : '보드 검증'}
        </button>
      ) : null}
    </section>
  );
}
