export type BotStatus = 'idle' | 'thinking' | 'moving' | 'error';
export type Difficulty = 'easy' | 'medium' | 'hard';
export type HumanColor = 'white' | 'black';
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
  bot_status?: BotStatus;
  last_bot_move?: string;
  auto_bot_move?: boolean;
  human_captures?: string[];
  robot_captures?: string[];
  difficulty?: Difficulty;
  move_history?: MoveRecord[];
  eval_cp?: number;
  bot_message?: string;
  bot_profile?: BotProfile;
  game_phase?: GamePhase;
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

export function squareName(col: number, row: number): string {
  return `${FILES[col]}${row + 1}`;
}

export function pieceImageUrl(piece: string): string {
  const map: Record<string, string> = {
    p: 'bP', r: 'bR', n: 'bN', b: 'bB', q: 'bQ', k: 'bK',
    P: 'wP', R: 'wR', N: 'wN', B: 'wB', Q: 'wQ', K: 'wK',
  };
  const key = map[piece] ?? piece;
  return `/pieces/cburnett/${key}.svg`;
}

export function cameraPreviewUrl(cacheBust: number): string {
  return `/api/camera/preview.jpg?t=${cacheBust}`;
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
): Promise<BoardResponse> {
  const res = await fetch('/api/game/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ human_color: humanColor, difficulty }),
  });
  const data = await readBoardResponse(res);
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? 'game config failed');
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
  if (board.bot_status === 'thinking') return '로봇 생각 중…';
  if (board.bot_status === 'moving') return '로봇 이동 중…';
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
  easy: '하',
  medium: '중',
  hard: '상',
};
