import { cameraPreviewUrl } from '../chess';

type Props = {
  cameraTick: number;
};

export default function CameraPanel({ cameraTick }: Props) {
  return (
    <div className="vision-panel vision-panel-realsense">
      <h3>RealSense (탑뷰)</h3>
      <img src={cameraPreviewUrl(cameraTick)} alt="RealSense 탑뷰 미리보기" />
    </div>
  );
}
