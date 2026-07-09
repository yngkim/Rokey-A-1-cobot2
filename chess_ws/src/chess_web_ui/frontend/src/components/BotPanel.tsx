import { BotProfile } from '../chess';

type Props = {
  profile: BotProfile;
  message: string;
  status: string;
  ttsMuted?: boolean;
  onToggleTtsMute?: () => void;
};

export default function BotPanel({ profile, message, status, ttsMuted, onToggleTtsMute }: Props) {
  const avatarLetter = profile.name.charAt(0);
  return (
    <>
      <div className="bot-header">
        <div className={`bot-avatar ${profile.avatar}`}>{avatarLetter}</div>
        <div>
          <div className="bot-name">{profile.name}</div>
          <div className="bot-meta">난이도 {profile.difficulty_label} · {status}</div>
        </div>
        {onToggleTtsMute ? (
          <button
            type="button"
            className={`tts-mute-btn${ttsMuted ? ' muted' : ''}`}
            onClick={onToggleTtsMute}
            title={ttsMuted ? '음성 켜기' : '음성 끄기'}
          >
            {ttsMuted ? '🔇' : '🔊'}
          </button>
        ) : null}
      </div>
      <div className="bot-chat">{message || '…'}</div>
    </>
  );
}
