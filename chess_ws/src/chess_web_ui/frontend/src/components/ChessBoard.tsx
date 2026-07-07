import {
  BoardResponse,
  HumanColor,
  parseFenBoard,
  pieceImageUrl,
  squareName,
} from '../chess';

type Props = {
  board: BoardResponse;
  humanColor: HumanColor;
  highlightSquares?: { from?: string; to?: string };
  editable?: boolean;
  draftGrid?: (string | null)[][];
  onSquareClick?: (square: string) => void;
};

export default function ChessBoard({
  board,
  humanColor,
  highlightSquares,
  editable = false,
  draftGrid,
  onSquareClick,
}: Props) {
  const fenBoard = draftGrid ?? parseFenBoard(board.fen);
  const flip = humanColor === 'black';
  const lastFrom = editable ? '' : (board.from ?? '');
  const lastTo = editable ? '' : (board.to ?? '');

  const displayRows = flip ? [...fenBoard].reverse() : fenBoard;

  return (
    <div className={`chess-board${editable ? ' chess-board-editing' : ''}`}>
      {displayRows.map((row, rowIdx) => {
        const rowFromTop = flip ? rowIdx : 7 - rowIdx;
        return (
          <div className="rank" key={`rank-${rowIdx}`}>
            {row.map((piece, col) => {
              const sq = squareName(col, rowFromTop);
              const light = (col + rowFromTop) % 2 === 0;
              const isLast =
                sq === lastFrom || sq === lastTo ||
                sq === highlightSquares?.from || sq === highlightSquares?.to;
              const hlFrom = sq === highlightSquares?.from;
              const hlTo = sq === highlightSquares?.to;
              const showFile = rowIdx === displayRows.length - 1;
              const showRank = col === 0;

              return (
                <div
                  key={sq}
                  role={editable ? 'button' : undefined}
                  tabIndex={editable ? 0 : undefined}
                  onClick={editable && onSquareClick ? () => onSquareClick(sq) : undefined}
                  onKeyDown={
                    editable && onSquareClick
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onSquareClick(sq);
                          }
                        }
                      : undefined
                  }
                  className={[
                    'square',
                    light ? 'light' : 'dark',
                    isLast ? 'last-move' : '',
                    hlFrom ? 'highlight-from' : '',
                    hlTo ? 'highlight-to' : '',
                    editable ? 'square-editable' : '',
                  ].filter(Boolean).join(' ')}
                >
                  {piece ? (
                    <img
                      className="piece-img"
                      src={pieceImageUrl(piece)}
                      alt={piece}
                      draggable={false}
                    />
                  ) : null}
                  {showFile ? (
                    <span className="coord file" style={{ color: light ? '#779556' : '#ebecd0' }}>
                      {sq[0]}
                    </span>
                  ) : null}
                  {showRank ? (
                    <span className="coord rank" style={{ color: light ? '#779556' : '#ebecd0' }}>
                      {sq[1]}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
