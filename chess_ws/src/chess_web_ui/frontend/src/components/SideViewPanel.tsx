import SideViewMiniBoard from './SideViewMiniBoard';
import {
  fetchTwinCalibration,
  fetchTwinLive,
  HumanColor,
  postTwinCalibration,
  TwinDetectionView,
  TwinLiveState,
  webcamPreviewUrl,
} from '../chess';
import { MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';

type Props = {
  cameraTick: number;
  humanColor: HumanColor;
  enabled: boolean;
  twinRuntimeEnabled?: boolean;
};

const EMPTY_LIVE: TwinLiveState = { enabled: false };
const CORNER_LABELS = ['a1', 'h1', 'h8', 'a8'];

const PIECE_NAMES: Record<string, string> = {
  P: '백 폰',
  N: '백 나이트',
  B: '백 비숍',
  R: '백 룩',
  Q: '백 퀸',
  K: '백 킹',
  p: '흑 폰',
  n: '흑 나이트',
  b: '흑 비숍',
  r: '흑 룩',
  q: '흑 퀸',
  k: '흑 킹',
};

function pieceLabel(det: TwinDetectionView): string {
  if (det.symbol) {
    const name = PIECE_NAMES[det.symbol] ?? det.class_name;
    return `${det.symbol} (${name})`;
  }
  return det.class_name;
}

function squareSortKey(square?: string): string {
  if (!square) return 'zz';
  return square;
}

function formatUpdatedAgo(updatedAt?: number): string {
  if (!updatedAt) return '';
  const sec = Math.max(0, Math.round(Date.now() / 1000 - updatedAt));
  if (sec < 1) return '방금 갱신';
  return `${sec}초 전 갱신`;
}

function cornersToPoints(boardCorners: number[]): { x: number; y: number }[] {
  const points: { x: number; y: number }[] = [];
  for (let i = 0; i < boardCorners.length; i += 2) {
    points.push({ x: boardCorners[i], y: boardCorners[i + 1] });
  }
  return points;
}

function pointsToCorners(points: { x: number; y: number }[]): number[] {
  return points.flatMap((pt) => [Math.round(pt.x), Math.round(pt.y)]);
}

export default function SideViewPanel({
  cameraTick,
  humanColor,
  enabled,
  twinRuntimeEnabled = false,
}: Props) {
  const [live, setLive] = useState<TwinLiveState>(EMPTY_LIVE);
  const [webcamBroken, setWebcamBroken] = useState(false);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [, setTick] = useState(0);
  const [calibrating, setCalibrating] = useState(false);
  const [draftCorners, setDraftCorners] = useState<{ x: number; y: number }[]>([]);
  const [flipFiles, setFlipFiles] = useState(false);
  const [boardFlipped, setBoardFlipped] = useState(false);
  const [calibrationMsg, setCalibrationMsg] = useState('');
  const [savingCalibration, setSavingCalibration] = useState(false);
  const previewRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    if (!enabled) {
      setLive(EMPTY_LIVE);
      setWebcamBroken(false);
      setPreviewLoaded(false);
      setCalibrating(false);
      setDraftCorners([]);
      return;
    }
    setWebcamBroken(false);
    setPreviewLoaded(false);
    let cancelled = false;
    let pollCount = 0;
    let timerId = 0;

    const load = async () => {
      try {
        const data = await fetchTwinLive();
        if (!cancelled) {
          setLive(data);
          if (data.preview_available) setPreviewLoaded(true);
        }
      } catch {
        if (!cancelled) setLive(EMPTY_LIVE);
      }
    };

    const schedule = () => {
      if (cancelled) return;
      void load();
      pollCount += 1;
      const delay = pollCount < 6 ? 300 : 500;
      timerId = window.setTimeout(schedule, delay);
    };
    timerId = window.setTimeout(schedule, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    void fetchTwinCalibration()
      .then((data) => {
        if (cancelled) return;
        setFlipFiles(Boolean(data.flip_files));
        setBoardFlipped(Boolean(data.board_flipped));
        if (data.board_corners?.length === 8) {
          setDraftCorners(cornersToPoints(data.board_corners));
        }
      })
      .catch(() => {
        if (!cancelled) setCalibrationMsg('캘리브레이션 정보를 불러오지 못했습니다');
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return undefined;
    const timer = window.setInterval(() => setTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [enabled]);

  const sortedDetections = useMemo(() => {
    const list = [...(live.sideview_detections ?? [])];
    list.sort((a, b) => squareSortKey(a.square).localeCompare(squareSortKey(b.square)));
    return list;
  }, [live.sideview_detections]);

  const handlePreviewClick = useCallback(
    (event: MouseEvent<HTMLImageElement>) => {
      if (!calibrating) return;
      const img = previewRef.current;
      if (!img || !img.naturalWidth || !img.naturalHeight) return;
      const rect = img.getBoundingClientRect();
      const scaleX = img.naturalWidth / rect.width;
      const scaleY = img.naturalHeight / rect.height;
      const x = (event.clientX - rect.left) * scaleX;
      const y = (event.clientY - rect.top) * scaleY;
      setDraftCorners((prev) => {
        if (prev.length >= 4) return [{ x, y }];
        return [...prev, { x, y }];
      });
      setCalibrationMsg('');
    },
    [calibrating],
  );

  const saveCalibration = async () => {
    if (draftCorners.length !== 4) {
      setCalibrationMsg('a1 → h1 → h8 → a8 순서로 4점을 클릭하세요');
      return;
    }
    setSavingCalibration(true);
    setCalibrationMsg('');
    try {
      const data = await postTwinCalibration({
        board_corners: pointsToCorners(draftCorners),
        flip_files: flipFiles,
        board_flipped: boardFlipped,
      });
      setLive((prev) => ({ ...prev, ...data }));
      setCalibrationMsg(data.message ?? '캘리브레이션을 저장했습니다');
      setCalibrating(false);
    } catch (err) {
      setCalibrationMsg(err instanceof Error ? err.message : '캘리브레이션 저장 실패');
    } finally {
      setSavingCalibration(false);
    }
  };

  if (!enabled) {
    return (
      <section className="sideview-section sideview-section-off">
        <p className="sideview-off-hint">
          손 감지 또는 사이드바 「사이드뷰 검증」을 켜면 웹캠 미리보기가 표시됩니다.
        </p>
      </section>
    );
  }

  const showTwinExtras = twinRuntimeEnabled && live.runtime_enabled !== false;

  const diffSquares = live.diff_squares ?? [];
  const pieceMap = live.sideview_piece_map ?? {};
  const mappedCount = Object.keys(pieceMap).length;
  const previewHint =
    live.preview_error ||
    (webcamBroken ? '웹캠 미리보기 로드 실패' : '') ||
    (!previewLoaded && live.preview_available === false
      ? '웹캠 프레임을 불러오는 중…'
      : '');
  const showPlaceholder = Boolean(previewHint) && !previewLoaded;
  const nextCornerLabel = CORNER_LABELS[draftCorners.length] ?? '';

  return (
    <section className="sideview-section">
      <div className="sideview-header-row">
        <h3 className="sideview-title">사이드뷰 (YOLO 참고용)</h3>
        <button
          type="button"
          className={`action-btn action-btn-secondary sideview-calibrate-btn${calibrating ? ' sideview-calibrate-btn-active' : ''}`}
          onClick={() => {
            setCalibrating((v) => !v);
            setCalibrationMsg('');
          }}
        >
          {calibrating ? '캘리브레이션 취소' : '보드 범위 캘리브레이션'}
        </button>
      </div>
      {calibrating ? (
        <div className="sideview-calibration-panel">
          <p className="sideview-calibration-hint">
            미리보기에서 보드 네 모서리를 순서대로 클릭하세요: a1 → h1 → h8 → a8
            {nextCornerLabel ? ` (다음: ${nextCornerLabel})` : ''}
          </p>
          <div className="sideview-calibration-options">
            <label>
              <input
                type="checkbox"
                checked={flipFiles}
                onChange={(e) => setFlipFiles(e.target.checked)}
              />
              파일(a-h) 좌우 반전
            </label>
            <label>
              <input
                type="checkbox"
                checked={boardFlipped}
                onChange={(e) => setBoardFlipped(e.target.checked)}
              />
              보드 180° 회전
            </label>
          </div>
          <div className="sideview-calibration-actions">
            <button
              type="button"
              className="action-btn action-btn-secondary"
              onClick={() => setDraftCorners([])}
              disabled={draftCorners.length === 0}
            >
              점 초기화
            </button>
            <button
              type="button"
              className="action-btn action-btn-primary"
              onClick={() => void saveCalibration()}
              disabled={draftCorners.length !== 4 || savingCalibration}
            >
              {savingCalibration ? '저장 중…' : '캘리브레이션 저장'}
            </button>
          </div>
        </div>
      ) : null}
      {calibrationMsg ? <p className="sideview-calibration-msg">{calibrationMsg}</p> : null}
      <div className={`vision-panel${calibrating ? ' vision-panel-calibrating' : ''}`}>
        {showPlaceholder ? (
          <div className="vision-panel-placeholder">{previewHint || '웹캠 미리보기 로드 실패'}</div>
        ) : null}
        <img
          ref={previewRef}
          src={webcamPreviewUrl(cameraTick)}
          alt="사이드뷰 웹캠 YOLO 인식 미리보기"
          onClick={handlePreviewClick}
          onError={() => setWebcamBroken(true)}
          onLoad={() => {
            setWebcamBroken(false);
            setPreviewLoaded(true);
          }}
          style={{
            cursor: calibrating ? 'crosshair' : 'default',
          }}
        />
      </div>
      <p className="sideview-detection-summary">
        {showTwinExtras ? (
          <>
            YOLO {sortedDetections.length}개 감지 · {mappedCount}칸 매핑
            {live.message ? ` · ${live.message}` : ''}
            {live.sideview_updated_at ? ` · YOLO ${formatUpdatedAgo(live.sideview_updated_at)}` : ''}
          </>
        ) : (
          <>사이드뷰 웹캠 라이브{live.hand_available ? ' · 손 감지 ON' : ''}</>
        )}
        {live.hand_safety_paused ? ' · 로봇 안전 일시정지' : ''}
        {live.preview_updated_at ? ` · 웹캠 ${formatUpdatedAgo(live.preview_updated_at)}` : ''}
      </p>
      {showTwinExtras && sortedDetections.length > 0 ? (
        <div className="sideview-detection-table-wrap">
          <table className="sideview-detection-table">
            <thead>
              <tr>
                <th>기물</th>
                <th>칸</th>
                <th>신뢰도</th>
                <th>좌표</th>
              </tr>
            </thead>
            <tbody>
              {sortedDetections.map((det, idx) => (
                <tr key={`${det.class_name}-${det.square}-${det.center_x}-${det.center_y}-${idx}`}>
                  <td>{pieceLabel(det)}</td>
                  <td>{det.square || '—'}</td>
                  <td>{det.confidence != null ? `${(det.confidence * 100).toFixed(0)}%` : '—'}</td>
                  <td>
                    {det.square
                      ? '—'
                      : `${Math.round(det.center_x ?? 0)}, ${Math.round(det.center_y ?? 0)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {showTwinExtras ? (
        <>
          <div className="mini-boards-row">
            <SideViewMiniBoard humanColor={humanColor} pieceMap={pieceMap} diffSquares={diffSquares} />
          </div>
          {diffSquares.length > 0 ? (
            <p className="vision-diff-summary">
              기록 보드와 사이드뷰 점유 차이 ({diffSquares.length}): {diffSquares.join(', ')}
            </p>
          ) : (
            <p className="vision-diff-summary vision-diff-ok">기록 보드와 사이드뷰 점유가 일치합니다.</p>
          )}
        </>
      ) : null}
    </section>
  );
}
