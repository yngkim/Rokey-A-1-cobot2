import { HumanColor, pieceImageUrl, squareName } from '../chess';

type Props = {
  humanColor: HumanColor;
  pieceMap: Record<string, string>;
  diffSquares: string[];
};

function pieceMapToGrid(pieceMap: Record<string, string>): (string | null)[][] {
  const grid: (string | null)[][] = Array.from({ length: 8 }, () => Array(8).fill(null));
  for (const [sq, piece] of Object.entries(pieceMap)) {
    if (sq.length < 2) continue;
    const file = sq.charCodeAt(0) - 'a'.charCodeAt(0);
    const rank = Number.parseInt(sq[1], 10) - 1;
    if (file < 0 || file > 7 || rank < 0 || rank > 7) continue;
    grid[7 - rank][file] = piece;
  }
  return grid;
}

export default function SideViewMiniBoard({ humanColor, pieceMap, diffSquares }: Props) {
  const flip = humanColor === 'black';
  const diffSet = new Set(diffSquares);
  const grid = pieceMapToGrid(pieceMap);
  const displayRows = flip
    ? [...grid].reverse().map((row) => [...row].reverse())
    : grid;

  return (
    <div className="mini-board-wrap">
      <p className="mini-board-label">사이드뷰 인식 (기록 보드와 다른 칸 강조)</p>
      <div className="mini-board">
        {displayRows.map((row, rowIdx) => {
          const rowFromTop = flip ? rowIdx : 7 - rowIdx;
          return (
            <div className="mini-rank" key={`mini-rank-${rowIdx}`}>
              {row.map((piece, col) => {
                const boardCol = flip ? 7 - col : col;
                const sq = squareName(boardCol, rowFromTop);
                const light = (boardCol + rowFromTop) % 2 === 0;
                const isDiff = diffSet.has(sq);
                return (
                  <div
                    key={sq}
                    className={[
                      'mini-square',
                      light ? 'light' : 'dark',
                      isDiff ? 'mini-square-diff' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    title={
                      piece
                        ? `${sq}: ${piece}${isDiff ? ' (기록 보드와 불일치)' : ''}`
                        : isDiff
                          ? `${sq}: 기록 보드와 사이드뷰 점유 불일치`
                          : sq
                    }
                  >
                    {piece ? (
                      <img className="mini-piece-img" src={pieceImageUrl(piece)} alt={piece} />
                    ) : null}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
