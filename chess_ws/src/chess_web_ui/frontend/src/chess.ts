export type BotStatus = 'idle' | 'thinking' | 'moving' | 'paused' | 'error';
export type Difficulty = 'beginner' | 'easy' | 'medium' | 'hard' | 'master';
export type HumanColor = 'white' | 'black';
export type BoardOrientation = 'standard' | 'flipped';
export type GamePhase = 'lobby' | 'playing' | 'finished';
export type MoveQuality = 'brilliant' | 'good' | 'inaccuracy' | 'mistake' | 'blunder';

export type MoveRecord = {
  ply: number;
  san: string;
  uci: string;
  from: string;
  to: string;
  color: string;
  eval_cp: number;
  quality?: MoveQuality;
};

export type BotProfile = {
  name: string;
  avatar: string;
  difficulty_label: string;
  greeting?: string;
};

export type GameResult =
  | 'checkmate'
  | 'stalemate'
  | 'insufficient_material'
  | 'fifty_moves'
  | 'repetition'
  | 'draw'
  | 'resign'
  | '';

export type BotSpeechKind =
  | 'greeting'
  | 'game_over'
  | 'check'
  | 'capture'
  | 'move'
  | 'illegal_move'
  | 'voice_move';

export type BoardResponse = {
  fen: string;
  occupancy: boolean[];
  message?: string;
  from?: string;
  to?: string;
  success?: boolean;
  white_to_move?: boolean;
  human_color?: HumanColor;
  robot_color?: HumanColor;
  board_orientation?: BoardOrientation;
  bot_status?: BotStatus;
  last_bot_move?: string;
  auto_bot_move?: boolean;
  human_captures?: string[];
  robot_captures?: string[];
  difficulty?: Difficulty;
  move_history?: MoveRecord[];
  eval_cp?: number;
  bot_message?: string;
  bot_speech_kind?: BotSpeechKind;
  bot_profile?: BotProfile;
  game_phase?: GamePhase;
  game_result?: GameResult;
  winner?: 'human' | 'robot' | 'draw' | '';
  is_check?: boolean;
  promotion_notice?: string;
  game_id?: string;
  graveyard_slots?: (string | null)[];
  human_graveyard_slots?: (string | null)[];
  undo_available?: boolean;
  promotion_required?: boolean;
  illegal_move?: boolean;
  parse_error?: boolean;
  transcript?: string;
  voice_action?: 'move' | 'confirm' | 'undo' | 'restore' | 'resign' | 'parse_error';
  parsed_summary?: string;
  twin_report?: TwinReport;
  twin_available?: boolean;
  twin_runtime_enabled?: boolean;
  hand_available?: boolean;
  hand_auto_confirm_enabled?: boolean;
};

export type TwinMismatch = {
  kind: string;
  square: string;
  message: string;
  recorded_symbol?: string;
  actual_symbol?: string;
  evidence?: string;
  authoritative?: boolean;
};

export type TwinSuggestion = {
  kind: string;
  message: string;
  candidate_fen?: string;
  priority?: number;
};

export type TwinReport = {
  success: boolean;
  aligned: boolean;
  message: string;
  recorded_fen: string;
  mismatches?: TwinMismatch[];
  suggestions?: TwinSuggestion[];
  scan_message?: string;
};

const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];

export function parseFenBoard(fen: string): (string | null)[][] {
  const rows = fen.split(' ')[0].split('/');
  return rows.map((row) => {
    const cells: (string | null)[] = [];
    for (const ch of row) {
      if (/\d/.test(ch)) {
        cells.push(...Array(Number(ch)).fill(null));
      } else {
        cells.push(ch);
      }
    }
    return cells;
  });
}

export function cloneBoardGrid(grid: (string | null)[][]): (string | null)[][] {
  return grid.map((row) => [...row]);
}

export function buildFenFromGrid(
  grid: (string | null)[][],
  activeColor: 'w' | 'b',
  fullmove = 1,
): string {
  const placement = grid
    .map((row) => {
      let fenRow = '';
      let empty = 0;
      for (const cell of row) {
        if (!cell) {
          empty += 1;
        } else {
          if (empty) {
            fenRow += String(empty);
            empty = 0;
          }
          fenRow += cell;
        }
      }
      if (empty) fenRow += String(empty);
      return fenRow || '8';
    })
    .join('/');
  return `${placement} ${activeColor} - - 0 ${fullmove}`;
}

export function countKings(grid: (string | null)[][]): { white: number; black: number } {
  let white = 0;
  let black = 0;
  for (const row of grid) {
    for (const cell of row) {
      if (cell === 'K') white += 1;
      if (cell === 'k') black += 1;
    }
  }
  return { white, black };
}

export function validateBoardGrid(grid: (string | null)[][]): string | null {
  const { white, black } = countKings(grid);
  if (white !== 1) return '백 킹은 정확히 1개여야 합니다';
  if (black !== 1) return '흑 킹은 정확히 1개여야 합니다';
  return null;
}

export type PalettePiece = string | null;

export const PIECE_PALETTE: { piece: PalettePiece; label: string }[] = [
  { piece: null, label: '지우기' },
  { piece: 'K', label: '♔' },
  { piece: 'Q', label: '♕' },
  { piece: 'R', label: '♖' },
  { piece: 'B', label: '♗' },
  { piece: 'N', label: '♘' },
  { piece: 'P', label: '♙' },
  { piece: 'k', label: '♚' },
  { piece: 'q', label: '♛' },
  { piece: 'r', label: '♜' },
  { piece: 'b', label: '♝' },
  { piece: 'n', label: '♞' },
  { piece: 'p', label: '♟' },
];

export function squareName(col: number, row: number): string {
  return `${FILES[col]}${row + 1}`;
}

export function squareNameToIndices(square: string): { col: number; row: number } {
  return { col: FILES.indexOf(square[0]), row: Number(square[1]) - 1 };
}

export function setSquarePiece(
  grid: (string | null)[][],
  square: string,
  piece: string | null,
): (string | null)[][] {
  const { col, row } = squareNameToIndices(square);
  const fenRow = 7 - row;
  const next = cloneBoardGrid(grid);
  next[fenRow][col] = piece;
  return next;
}

export function pieceImageUrl(piece: string): string {
  const map: Record<string, string> = {
    p: 'bP', r: 'bR', n: 'bN', b: 'bB', q: 'bQ', k: 'bK',
    P: 'wP', R: 'wR', N: 'wN', B: 'wB', Q: 'wQ', K: 'wK',
  };
  const key = map[piece] ?? piece;
  return `/pieces/cburnett/${key}.svg`;
}

export type GraveyardSide = 'black' | 'white';

export function graveyardSlotLabel(side: GraveyardSide, col: number, graveRow: number): string {
  if (side === 'white') {
    if (graveRow === 0) return `${FILES[col]}0`;
    return `${FILES[col]}-1`;
  }
  return `${FILES[col]}${9 + graveRow}`;
}

export function graveyardSlotIndex(col: number, graveRow: number): number {
  return graveRow * 8 + col;
}

export function graveyardFillOrder(side: GraveyardSide): [number, number][] {
  if (side === 'white') {
    const row0 = Array.from({ length: 8 }, (_, col) => [col, 0] as [number, number]);
    const row1 = Array.from({ length: 8 }, (_, col) => [col, 1] as [number, number]);
    return [...row0, ...row1];
  }
  const row0 = Array.from({ length: 8 }, (_, i) => [7 - i, 0] as [number, number]);
  const row1 = Array.from({ length: 8 }, (_, i) => [7 - i, 1] as [number, number]);
  return [...row0, ...row1];
}

export function graveyardDisplayRows(side: GraveyardSide): [number, number][][] {
  const order = graveyardFillOrder(side);
  return [order.slice(0, 8), order.slice(8, 16)];
}

export function robotGraveyardSide(humanColor: HumanColor): GraveyardSide {
  return humanColor === 'white' ? 'black' : 'white';
}

export function cameraPreviewUrl(cacheBust: number): string {
  return `/api/camera/preview.jpg?t=${cacheBust}`;
}

export function webcamPreviewUrl(cacheBust: number): string {
  return `/api/twin/webcam/preview.jpg?t=${cacheBust}`;
}

export function handPreviewUrl(cacheBust: number): string {
  return `/api/hand/preview.jpg?t=${cacheBust}`;
}

export type TwinDetectionView = {
  class_name: string;
  symbol?: string;
  square?: string;
  confidence?: number;
  center_x?: number;
  center_y?: number;
  bbox?: number[];
};

export type TwinLiveState = {
  enabled: boolean;
  available?: boolean;
  runtime_enabled?: boolean;
  recorded_occupancy?: boolean[];
  sideview_occupancy?: boolean[];
  sideview_piece_map?: Record<string, string>;
  sideview_detections?: TwinDetectionView[];
  diff_squares?: string[];
  message?: string;
  preview_available?: boolean;
  preview_error?: string;
  sideview_updated_at?: number;
  preview_updated_at?: number;
  hand_in_board?: boolean;
  hand_seen?: boolean;
  hand_present?: boolean;
  hand_updated_at?: number;
  hand_safety_paused?: boolean;
  hand_auto_confirm_enabled?: boolean;
  hand_available?: boolean;
  hand_preview_available?: boolean;
  hand_preview_error?: string;
  hand_detection_count?: number;
};

export type TwinCalibrationState = {
  calibration_path?: string;
  board_corners: number[];
  flip_files: boolean;
  board_flipped: boolean;
  webcam_device?: number;
  camera_width?: number;
  camera_height?: number;
};

export async function fetchTwinCalibration(): Promise<TwinCalibrationState> {
  const res = await fetch('/api/twin/calibration');
  if (!res.ok) throw new Error('failed to fetch twin calibration');
  return (await res.json()) as TwinCalibrationState;
}

export async function postTwinCalibration(payload: {
  board_corners: number[];
  flip_files?: boolean;
  board_flipped?: boolean;
}): Promise<TwinCalibrationState & TwinLiveState & { success?: boolean; message?: string }> {
  const res = await fetch('/api/twin/calibration', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'twin calibration save failed');
  return data as TwinCalibrationState & TwinLiveState & { success?: boolean; message?: string };
}

export async function fetchTwinLive(): Promise<TwinLiveState> {
  const res = await fetch('/api/twin/live');
  if (!res.ok) throw new Error('failed to fetch twin live state');
  return (await res.json()) as TwinLiveState;
}

export async function readBoardResponse(res: Response): Promise<BoardResponse> {
  const text = await res.text();
  try {
    return JSON.parse(text) as BoardResponse;
  } catch {
    throw new Error(text.startsWith('Internal') ? '서버 오류가 발생했습니다' : text || 'invalid response');
  }
}

export async function fetchBoard(): Promise<BoardResponse> {
  const res = await fetch('/api/board');
  if (!res.ok) throw new Error('failed to fetch board');
  return readBoardResponse(res);
}

export async function postGameConfig(
  humanColor: HumanColor,
  difficulty: Difficulty,
  boardOrientation: BoardOrientation = 'standard',
  handAutoConfirmEnabled?: boolean,
): Promise<BoardResponse> {
  const res = await fetch('/api/game/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      human_color: humanColor,
      difficulty,
      board_orientation: boardOrientation,
      hand_auto_confirm_enabled: handAutoConfirmEnabled,
    }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'game config failed');
  return data;
}

export async function postHandConfig(enabled: boolean): Promise<BoardResponse> {
  const res = await fetch('/api/hand/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto_confirm_enabled: enabled }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'hand config failed');
  return data;
}

export async function postPlayerMoved(): Promise<BoardResponse> {
  const res = await fetch('/api/player-moved', { method: 'POST' });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'player move detection failed');
  return data;
}

export async function resetBoard(): Promise<BoardResponse> {
  const res = await fetch('/api/reset', { method: 'POST' });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'reset failed');
  return data;
}

export async function restoreBoard(): Promise<BoardResponse> {
  const res = await fetch('/api/restore_board', { method: 'POST' });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'restore failed');
  return data;
}

export async function postPlayerPromote(piece: string): Promise<BoardResponse> {
  const res = await fetch('/api/player-moved/promote', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ piece }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'promotion failed');
  return data;
}

export async function postBoardCorrect(
  fen: string,
  graveyards?: {
    graveyard_slots?: (string | null)[];
    human_graveyard_slots?: (string | null)[];
  },
): Promise<BoardResponse> {
  const res = await fetch('/api/board/correct', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fen, ...graveyards }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'board correction failed');
  return data;
}

export async function postResign(): Promise<BoardResponse> {
  const res = await fetch('/api/resign', { method: 'POST' });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'resign failed');
  return data;
}

export async function postUndo(): Promise<BoardResponse> {
  const res = await fetch('/api/undo', { method: 'POST' });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'undo failed');
  return data;
}

export async function postRevertIllegalMove(from: string, to: string): Promise<BoardResponse> {
  const res = await fetch('/api/revert-illegal-move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from, to }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'revert failed');
  return data;
}

export async function postTwinVerify(options?: {
  confirm_failed?: boolean;
  use_fresh_scan?: boolean;
}): Promise<BoardResponse> {
  const res = await fetch('/api/twin/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      confirm_failed: options?.confirm_failed ?? false,
      use_fresh_scan: options?.use_fresh_scan ?? true,
    }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'twin verify failed');
  return data;
}

export async function postTwinConfig(enabled: boolean): Promise<BoardResponse> {
  const res = await fetch('/api/twin/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'twin config failed');
  return data;
}

export async function postVoiceMove(transcript: string): Promise<BoardResponse> {
  const res = await fetch('/api/voice-move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transcript }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'voice move failed');
  return data;
}

export function pieceLabel(piece: string | null): string {
  if (!piece) return '';
  const map: Record<string, string> = {
    p: '♟', r: '♜', n: '♞', b: '♝', q: '♛', k: '♚',
    P: '♙', R: '♖', N: '♘', B: '♗', Q: '♕', K: '♔',
  };
  return map[piece] ?? piece;
}

export function isHumanTurn(board: BoardResponse | null): boolean {
  if (!board || board.white_to_move === undefined || !board.human_color) return true;
  const humanIsWhite = board.human_color === 'white';
  return board.white_to_move === humanIsWhite;
}

export function turnLabel(board: BoardResponse | null): string {
  if (!board) return '';
  if (board.game_phase === 'finished') {
    if (board.game_result === 'checkmate') {
      if (board.winner === 'human') return '체크메이트 — 당신 승리';
      if (board.winner === 'robot') return '체크메이트 — 봇 승리';
    }
    if (board.game_result === 'stalemate') return '스테일메이트 — 무승부';
    if (board.game_result === 'resign') {
      if (board.winner === 'robot') return '기권 — 패배';
      return '기권';
    }
    return '게임 종료 — 무승부';
  }
  if (board.is_check && isHumanTurn(board)) return '체크! 당신 차례';
  if (board.is_check) return '체크!';
  if (board.bot_status === 'thinking') return '로봇 생각 중…';
  if (board.bot_status === 'moving') return '로봇 이동 중…';
  if (board.bot_status === 'paused') return '손 감지 — 로봇 일시정지';
  if (board.bot_status === 'error') return '로봇 오류';
  if (!isHumanTurn(board)) {
    return `차례: ${board.robot_color === 'white' ? '백' : '흑'}(로봇)`;
  }
  return `차례: ${board.human_color === 'white' ? '백' : '흑'}(당신)`;
}

export function evalToPercent(evalCp: number): number {
  const clamped = Math.max(-800, Math.min(800, evalCp));
  return 50 + (clamped / 800) * 50;
}

export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  beginner: '입문',
  easy: '하',
  medium: '중',
  hard: '상',
  master: '최상',
};
