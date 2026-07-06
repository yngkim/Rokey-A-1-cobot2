import { cameraPreviewUrl } from '../chess';

type Props = {
  cameraTick: number;
};

export default function CameraPanel({ cameraTick }: Props) {
  return (
    <div className="camera-below">
      <h3>탑뷰 카메라</h3>
      <img
        src={cameraPreviewUrl(cameraTick)}
        alt="탑뷰 비전 미리보기"
      />
    </div>
  );
}
