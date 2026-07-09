type Props = {
  onConfirm: () => void;
  onReset: () => void;
  onRestore: () => void;
  onEdit: () => void;
  onResign: () => void;
  onUndo: () => void;
  onVoiceMove: () => void;
  confirmDisabled: boolean;
  confirmBusy: boolean;
  resetDisabled: boolean;
  restoreDisabled: boolean;
  editDisabled: boolean;
  resignDisabled: boolean;
  undoDisabled: boolean;
  undoBusy: boolean;
  voiceDisabled: boolean;
  voiceListening: boolean;
  voiceInterimText?: string;
  editing: boolean;
  restoreBusy: boolean;
};

export default function GameActionBar({
  onConfirm,
  onReset,
  onRestore,
  onEdit,
  onResign,
  onUndo,
  onVoiceMove,
  confirmDisabled,
  confirmBusy,
  resetDisabled,
  restoreDisabled,
  editDisabled,
  resignDisabled,
  undoDisabled,
  undoBusy,
  voiceDisabled,
  voiceListening,
  voiceInterimText,
  editing,
  restoreBusy,
}: Props) {
  const handleResign = () => {
    if (!window.confirm('정말 기권하시겠습니까?')) return;
    onResign();
  };

  return (
    <div className="game-action-bar-wrap">
      <div className="game-action-bar">
        <button
          type="button"
          className="action-btn action-btn-primary"
          onClick={onConfirm}
          disabled={confirmDisabled || confirmBusy || editing || voiceListening}
        >
          {confirmBusy ? '감지 중…' : '수 두었음'}
        </button>
        <button
          type="button"
          className={`action-btn action-btn-secondary voice-move-btn${voiceListening ? ' voice-move-btn-listening' : ''}`}
          onClick={onVoiceMove}
          disabled={voiceDisabled || confirmBusy || editing || voiceListening}
          title="음성으로 수 명령 (약 5초)"
        >
          {voiceListening ? '듣는 중…' : '🎤 음성 명령'}
        </button>
        <button
          type="button"
          className="action-btn action-btn-secondary"
          onClick={onUndo}
          disabled={undoDisabled || confirmBusy || editing || undoBusy || voiceListening}
        >
          {undoBusy ? '되돌리는 중…' : 'Undo'}
        </button>
        <button
          type="button"
          className="action-btn action-btn-secondary"
          onClick={onReset}
          disabled={resetDisabled || confirmBusy || editing || voiceListening}
        >
          Reset
        </button>
        <button
          type="button"
          className="action-btn action-btn-secondary"
          onClick={onRestore}
          disabled={restoreDisabled || confirmBusy || editing || restoreBusy || voiceListening}
        >
          {restoreBusy ? '정리 중…' : '보드 정리'}
        </button>
        <button
          type="button"
          className="action-btn action-btn-secondary"
          onClick={onEdit}
          disabled={editDisabled || confirmBusy || editing || voiceListening}
        >
          보드 수정
        </button>
        <button
          type="button"
          className="action-btn action-btn-danger"
          onClick={handleResign}
          disabled={resignDisabled || confirmBusy || editing || voiceListening}
        >
          기권
        </button>
      </div>
      {voiceListening ? (
        <p className="voice-interim-line" role="status">
          {voiceInterimText
            ? `인식 중: ${voiceInterimText}`
            : '말씀해 주세요… (약 5초)'}
        </p>
      ) : null}
    </div>
  );
}
