import { fetchTwinLive, handPreviewUrl, TwinLiveState } from '../chess';
import { useEffect, useState } from 'react';

type Props = {
  cameraTick: number;
  enabled: boolean;
};

const EMPTY_LIVE: TwinLiveState = { enabled: false };

function formatUpdatedAgo(updatedAt?: number): string {
  if (!updatedAt) return '';
  const sec = Math.max(0, Math.round(Date.now() / 1000 - updatedAt));
  if (sec < 1) return '방금 갱신';
  return `${sec}초 전 갱신`;
}

function handStatusLabel(live: TwinLiveState): string {
  if (live.hand_in_board) return '보드 위 손 감지 중';
  if (live.hand_present) return '손 감지 (보드 밖)';
  if (live.hand_seen) return '손 감지 (ROI 확인 중)';
  return '손 없음';
}

export default function HandViewPanel({ cameraTick, enabled }: Props) {
  const [live, setLive] = useState<TwinLiveState>(EMPTY_LIVE);
  const [previewBroken, setPreviewBroken] = useState(false);
  const [previewLoaded, setPreviewLoaded] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setLive(EMPTY_LIVE);
      setPreviewBroken(false);
      setPreviewLoaded(false);
      return;
    }
    let cancelled = false;
    let timerId = 0;

    const load = async () => {
      try {
        const data = await fetchTwinLive();
        if (!cancelled) {
          setLive(data);
          if (data.hand_preview_available) setPreviewLoaded(true);
        }
      } catch {
        if (!cancelled) setLive(EMPTY_LIVE);
      }
    };

    const schedule = () => {
      if (cancelled) return;
      void load();
      timerId = window.setTimeout(schedule, 300);
    };
    timerId = window.setTimeout(schedule, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
    };
  }, [enabled]);

  if (!enabled) return null;

  const previewHint =
    live.hand_preview_error ||
    (previewBroken ? '손 감지 미리보기 로드 실패' : '') ||
    (!previewLoaded && !live.hand_preview_available ? '손 감지 프레임을 불러오는 중…' : '');
  const showPlaceholder = Boolean(previewHint) && !previewLoaded;

  return (
    <section className="sideview-section handview-section">
      <h3 className="sideview-title">손 감지 (YOLO 전용)</h3>
      <div className="vision-panel">
        {showPlaceholder ? (
          <div className="vision-panel-placeholder">{previewHint}</div>
        ) : null}
        <img
          src={handPreviewUrl(cameraTick)}
          alt="손 감지 YOLO 미리보기"
          onError={() => setPreviewBroken(true)}
          onLoad={() => {
            setPreviewBroken(false);
            setPreviewLoaded(true);
          }}
        />
      </div>
      <p className="sideview-detection-summary">
        {handStatusLabel(live)}
        {live.hand_detection_count != null ? ` · 감지 ${live.hand_detection_count}개` : ''}
        {live.hand_auto_confirm_enabled ? ' · 자동 수 확인 ON' : ' · 자동 수 확인 OFF'}
        {live.hand_safety_paused ? ' · 로봇 안전 일시정지' : ''}
        {live.hand_updated_at ? ` · ${formatUpdatedAgo(live.hand_updated_at)}` : ''}
        {live.preview_updated_at ? ` · 웹캠 ${formatUpdatedAgo(live.preview_updated_at)}` : ''}
      </p>
      <p className="handview-flow-hint">
        빨간 박스 = 보드 안 손 · 주황 = 보드 밖 · 손이 사라지면 RealSense로 수를 확인하고 로봇이 응수합니다.
      </p>
    </section>
  );
}
