import { evalToPercent } from '../chess';

type Props = {
  evalCp: number;
  humanColor: 'white' | 'black';
};

export default function EvalBar({ evalCp, humanColor }: Props) {
  const humanAdvantage = humanColor === 'white' ? evalCp : -evalCp;
  const whitePercent = evalToPercent(evalCp);
  const label =
    Math.abs(humanAdvantage) < 30
      ? '균형'
      : humanAdvantage > 0
        ? `당신 +${(humanAdvantage / 100).toFixed(1)}`
        : `봇 +${(-humanAdvantage / 100).toFixed(1)}`;

  return (
    <div className="eval-bar-wrap">
      <div className="eval-bar" title={`eval: ${evalCp}cp`}>
        <div className="eval-bar-fill" style={{ width: `${whitePercent}%` }} />
      </div>
      <div className="eval-label">{label}</div>
    </div>
  );
}
