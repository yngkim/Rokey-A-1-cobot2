type Props = {
  botLabel: string;
  botTime: string;
  botActive: boolean;
  botError: boolean;
  playerLabel: string;
  playerTime: string;
  playerActive: boolean;
};

export default function ClockConfirmButton({
  botLabel,
  botTime,
  botActive,
  botError,
  playerLabel,
  playerTime,
  playerActive,
}: Props) {
  return (
    <div className="clock-row">
      <div className={`clock bot-clock ${botActive ? 'active' : ''} ${botError ? 'error' : ''}`}>
        <div className="clock-label">{botLabel}</div>
        <div className="clock-time">{botTime}</div>
      </div>
      <div className={`clock ${playerActive ? 'active' : ''}`}>
        <div className="clock-label">{playerLabel}</div>
        <div className="clock-time">{playerTime}</div>
      </div>
    </div>
  );
}
