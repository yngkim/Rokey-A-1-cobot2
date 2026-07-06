import { BotProfile } from '../chess';

type Props = {
  profile: BotProfile;
  message: string;
  status: string;
};

export default function BotPanel({ profile, message, status }: Props) {
  const avatarLetter = profile.name.charAt(0);
  return (
    <>
      <div className="bot-header">
        <div className={`bot-avatar ${profile.avatar}`}>{avatarLetter}</div>
        <div>
          <div className="bot-name">{profile.name}</div>
          <div className="bot-meta">난이도 {profile.difficulty_label} · {status}</div>
        </div>
      </div>
      <div className="bot-chat">{message || '…'}</div>
    </>
  );
}
