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

export type GameResult =
  | 'checkmate'
  | 'stalemate'
  | 'insufficient_material'
  | 'fifty_moves'
  | 'repetition'
  | 'draw'
  | '';

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
  game_result?: GameResult;
  winner?: 'human' | 'robot' | 'draw' | '';
  is_check?: boolean;
  promotion_notice?: string;
  game_id?: string;
  graveyard_slots?: (string | null)[];
  human_graveyard_slots?: (string | null)[];
  promotion_required?: boolean;
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
    return '게임 종료 — 무승부';
  }
  if (board.is_check && isHumanTurn(board)) return '체크! 당신 차례';
  if (board.is_check) return '체크!';
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
