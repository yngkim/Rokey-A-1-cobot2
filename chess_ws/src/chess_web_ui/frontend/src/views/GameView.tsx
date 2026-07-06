import { useMemo, useState } from 'react';
import {
  BoardResponse,
  HumanColor,
  isHumanTurn,
  turnLabel,
} from '../chess';
import BotPanel from '../components/BotPanel';
import CameraPanel from '../components/CameraPanel';
import CapturedBar from '../components/CapturedBar';
import ChessBoard from '../components/ChessBoard';
import ClockConfirmButton from '../components/ClockConfirmButton';
import EvalBar from '../components/EvalBar';
import GameActionBar from '../components/GameActionBar';
import MoveList from '../components/MoveList';

type Props = {
  board: BoardResponse;
  humanColor: HumanColor;
  cameraTick: number;
  busy: boolean;
  onConfirmMove: () => void;
  onReset: () => void;
  onBackToLobby: () => void;
};

export default function GameView({
  board,
  humanColor,
  cameraTick,
  busy,
  onConfirmMove,
  onReset,
  onBackToLobby,
}: Props) {
  const [selectedPly, setSelectedPly] = useState<number | null>(null);

  const humanTurn = isHumanTurn(board);
  const botBusy = board.bot_status === 'thinking' || board.bot_status === 'moving';
  const profile = board.bot_profile ?? {
    name: '봇',
    avatar: 'medium',
    difficulty_label: '중',
  };

  const highlight = useMemo(() => {
    if (selectedPly == null) return undefined;
    const move = board.move_history?.find((m) => m.ply === selectedPly);
    if (!move) return undefined;
    return { from: move.from, to: move.to };
  }, [selectedPly, board.move_history]);

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

  return (
    <>
      <div className="game-topbar">
        <span className="status-line">{turnLabel(board) || board.message}</span>
        <button type="button" onClick={onBackToLobby} disabled={busy || botBusy}>
          로비로
        </button>
      </div>

      <div className="game-layout">
        <div className="board-column">
          <GameActionBar
            onConfirm={onConfirmMove}
            onReset={onReset}
            confirmDisabled={!humanTurn || botBusy}
            confirmBusy={busy}
            resetDisabled={botBusy}
          />
          <CapturedBar pieces={topCaptures} />
          <ChessBoard board={board} humanColor={humanColor} highlightSquares={highlight} />
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
            status={turnLabel(board)}
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
