import { useEffect, useMemo, useState } from 'react';
import {
  BoardResponse,
  HumanColor,
  PalettePiece,
  buildFenFromGrid,
  cloneBoardGrid,
  isHumanTurn,
  parseFenBoard,
  robotGraveyardSide,
  setSquarePiece,
  turnLabel,
  validateBoardGrid,
} from '../chess';
import BoardEditBar from '../components/BoardEditBar';
import BotPanel from '../components/BotPanel';
import CameraPanel from '../components/CameraPanel';
import CapturedBar from '../components/CapturedBar';
import ChessBoard from '../components/ChessBoard';
import ClockConfirmButton from '../components/ClockConfirmButton';
import EvalBar from '../components/EvalBar';
import GraveyardEditGrid from '../components/GraveyardEditGrid';
import GameActionBar from '../components/GameActionBar';
import MoveList from '../components/MoveList';

type Props = {
  board: BoardResponse;
  humanColor: HumanColor;
  cameraTick: number;
  busy: boolean;
  ttsMuted: boolean;
  onToggleTtsMute: () => void;
  onConfirmMove: () => void;
  onReset: () => void;
  onRestore: () => void;
  onBackToLobby: () => void;
  onResign: () => void;
  onUndo: () => void;
  onVoiceMove: () => void;
  voiceListening: boolean;
  voiceInterimText?: string;
  onBoardCorrect: (
    fen: string,
    graveyards?: {
      graveyard_slots?: (string | null)[];
      human_graveyard_slots?: (string | null)[];
    },
  ) => Promise<void>;
  boardEditRequest?: number;
};

export default function GameView({
  board,
  humanColor,
  cameraTick,
  busy,
  ttsMuted,
  onToggleTtsMute,
  onConfirmMove,
  onReset,
  onRestore,
  onBackToLobby,
  onResign,
  onUndo,
  onVoiceMove,
  voiceListening,
  voiceInterimText,
  onBoardCorrect,
  boardEditRequest = 0,
}: Props) {
  const [selectedPly, setSelectedPly] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [draftGrid, setDraftGrid] = useState<(string | null)[][] | null>(null);
  const [draftWhiteToMove, setDraftWhiteToMove] = useState(true);
  const [selectedPiece, setSelectedPiece] = useState<PalettePiece>('P');
  const [draftRobotGraveyard, setDraftRobotGraveyard] = useState<(string | null)[]>([]);
  const [draftHumanGraveyard, setDraftHumanGraveyard] = useState<(string | null)[]>([]);
  const [saving, setSaving] = useState(false);

  const emptyGraveyard = () => Array.from({ length: 16 }, () => null as string | null);

  const humanTurn = isHumanTurn(board);
  const botBusy = board.bot_status === 'thinking' || board.bot_status === 'moving';
  const gameFinished = board.game_phase === 'finished';

  const gameOverTitle = useMemo(() => {
    if (!gameFinished) return '';
    if (board.game_result === 'checkmate') {
      if (board.winner === 'human') return '체크메이트 — 승리!';
      if (board.winner === 'robot') return '체크메이트 — 패배';
      return '체크메이트';
    }
    if (board.game_result === 'stalemate') return '스테일메이트 — 무승부';
    if (board.game_result === 'resign') return '기권 — 패배';
    return '무승부';
  }, [board.game_result, board.winner, gameFinished]);

  const profile = board.bot_profile ?? {
    name: '봇',
    avatar: 'medium',
    difficulty_label: '중',
  };

  const highlight = useMemo(() => {
    if (editing || selectedPly == null) return undefined;
    const move = board.move_history?.find((m) => m.ply === selectedPly);
    if (!move) return undefined;
    return { from: move.from, to: move.to };
  }, [editing, selectedPly, board.move_history]);

  const validationError = useMemo(() => {
    if (!editing || !draftGrid) return null;
    return validateBoardGrid(draftGrid);
  }, [editing, draftGrid]);

  const botClockText =
    board.bot_status === 'thinking'
      ? '생각…'
      : board.bot_status === 'moving'
        ? '이동…'
        : board.bot_status === 'error'
          ? '오류'
          : '대기';

  const playerClockText = humanTurn ? '당신 차례' : '대기';

  const topCaptures =
    humanColor === 'white' ? board.robot_captures ?? [] : board.human_captures ?? [];
  const bottomCaptures =
    humanColor === 'white' ? board.human_captures ?? [] : board.robot_captures ?? [];

  const startEditing = () => {
    setDraftGrid(cloneBoardGrid(parseFenBoard(board.fen)));
    setDraftWhiteToMove(board.white_to_move ?? true);
    setDraftRobotGraveyard([...(board.graveyard_slots ?? emptyGraveyard())]);
    setDraftHumanGraveyard([...(board.human_graveyard_slots ?? emptyGraveyard())]);
    setSelectedPiece('P');
    setEditing(true);
    setSelectedPly(null);
  };

  useEffect(() => {
    if (boardEditRequest > 0) {
      startEditing();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boardEditRequest]);

  const cancelEditing = () => {
    setEditing(false);
    setDraftGrid(null);
    setDraftRobotGraveyard([]);
    setDraftHumanGraveyard([]);
    setSaving(false);
  };

  const handleSquareClick = (square: string) => {
    if (!draftGrid) return;
    setDraftGrid(setSquarePiece(draftGrid, square, selectedPiece));
  };

  const handleSave = async () => {
    if (!draftGrid || validationError) return;
    const fen = buildFenFromGrid(draftGrid, draftWhiteToMove ? 'w' : 'b');
    setSaving(true);
    try {
      await onBoardCorrect(fen, {
        graveyard_slots: draftRobotGraveyard,
        human_graveyard_slots: draftHumanGraveyard,
      });
      setEditing(false);
      setDraftGrid(null);
      setDraftRobotGraveyard([]);
      setDraftHumanGraveyard([]);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="game-topbar">
        <span className="status-line">
          {editing ? '보드 수정 모드 — 팔레트를 고른 뒤 칸을 클릭하세요' : turnLabel(board) || board.message}
        </span>
        <button type="button" onClick={onBackToLobby} disabled={busy || botBusy || editing}>
          로비로
        </button>
      </div>

      {board.promotion_notice ? (
        <div className="promotion-notice" role="status">
          {board.promotion_notice}
        </div>
      ) : null}

      {gameFinished ? (
        <div className="game-over-banner" role="status">
          <strong>{gameOverTitle}</strong>
          <span>{board.bot_message}</span>
        </div>
      ) : null}

      <div className="game-layout">
        <div className="board-column">
          <GameActionBar
            onConfirm={onConfirmMove}
            onReset={onReset}
            onRestore={onRestore}
            onEdit={startEditing}
            onResign={onResign}
            onUndo={onUndo}
            onVoiceMove={onVoiceMove}
            confirmDisabled={!humanTurn || botBusy || gameFinished}
            confirmBusy={busy}
            voiceDisabled={!humanTurn || botBusy || gameFinished || busy}
            voiceListening={voiceListening}
            voiceInterimText={voiceInterimText}
            resetDisabled={botBusy || busy}
            restoreDisabled={botBusy || busy}
            restoreBusy={busy}
            editDisabled={botBusy || busy}
            resignDisabled={botBusy || busy || gameFinished}
            undoDisabled={botBusy || busy || gameFinished || !board.undo_available}
            undoBusy={busy}
            editing={editing}
          />
          {editing && draftGrid ? (
            <BoardEditBar
              selectedPiece={selectedPiece}
              whiteToMove={draftWhiteToMove}
              validationError={validationError}
              saveDisabled={validationError !== null}
              busy={saving}
              onSelectPiece={setSelectedPiece}
              onToggleTurn={() => setDraftWhiteToMove((v) => !v)}
              onSave={handleSave}
              onCancel={cancelEditing}
            />
          ) : null}
          {editing ? (
            <div className="graveyard-edit-row">
              <GraveyardEditGrid
                title="로봇 graveyard"
                side={robotGraveyardSide(humanColor)}
                slots={draftRobotGraveyard}
                selectedPiece={selectedPiece}
                onChange={setDraftRobotGraveyard}
              />
              <GraveyardEditGrid
                title="사용자 graveyard"
                side={humanColor}
                slots={draftHumanGraveyard}
                selectedPiece={selectedPiece}
                onChange={setDraftHumanGraveyard}
              />
            </div>
          ) : null}
          <CapturedBar pieces={topCaptures} />
          <ChessBoard
            board={board}
            humanColor={humanColor}
            highlightSquares={highlight}
            editable={editing}
            draftGrid={editing ? draftGrid ?? undefined : undefined}
            onSquareClick={handleSquareClick}
          />
          <CapturedBar pieces={bottomCaptures} />
          <CameraPanel cameraTick={cameraTick} />
          <ClockConfirmButton
            botLabel={profile.name}
            botTime={botClockText}
            botActive={!humanTurn}
            botError={board.bot_status === 'error'}
            playerLabel="당신"
            playerTime={playerClockText}
            playerActive={humanTurn}
          />
        </div>

        <aside className="sidebar">
          <BotPanel
            profile={profile}
            message={board.bot_message ?? ''}
            status={editing ? '보드 수정 중' : turnLabel(board)}
            ttsMuted={ttsMuted}
            onToggleTtsMute={onToggleTtsMute}
          />
          <EvalBar evalCp={board.eval_cp ?? 0} humanColor={humanColor} />
          <MoveList
            moves={board.move_history ?? []}
            selectedPly={selectedPly}
            onSelect={setSelectedPly}
          />
        </aside>
      </div>
    </>
  );
}
