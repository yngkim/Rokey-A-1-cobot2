# Chess Piece Detector

## 폴더 구성
- weights/: 학습된 YOLO11 모델
- code/: 탐지 및 좌표 계산 로직
- calibration/: 좌표 설정에 쓰인 빈 체스판 원본 사진 (카메라 위치 바뀌면 재조정 시 참고)
- sample_images/: 테스트용 샘플 사진

## 설치
\`\`\`
pip install -r requirements.txt
\`\`\`

## 사용법
\`\`\`python
from chess_detector import ChessDetector

detector = ChessDetector(model_path="weights/chess_final_side1_best.pt")
results = detector.detect("sample_images/20260708_140531_712.jpg")

for r in results:
    print(f"{r['class']} | conf: {r['confidence']} | square: {r['square']}")
\`\`\`

## 주의사항
- config.py의 BOARD_CORNERS는 특정 카메라 위치/각도 기준으로 고정된 값입니다.
- 카메라 위치가 바뀌면 calibration/empty_board.jpg로 좌표를 다시 잡아야 합니다.
- 카메라가 고정이라면 이 값은 그대로 재사용 가능합니다.

## 체스 트윈(Reality Check) 사이드뷰 캘리브레이션

**판단 우선순위**: RealSense 점유가 1차 기준입니다. 사이드뷰 YOLO는 정확도가 낮아 **참고용**으로만 표시하며, 매 수마다 어느 쪽이 맞는지 묻지 않습니다.

웹 UI `board_twin`은 별도 설정 파일을 사용합니다.

- 설정 파일: `chess_ws/src/chess_web_ui/config/board_twin_side_calibration.json`
- launch 인자: `twin_calibration_path`, `twin_webcam_device` (C270 권장: `10`), `twin_model_path` (기본: `model/weights/chess_final_side1_best.pt`)

### 손 감지 (hand YOLO)

- 모델: `hand_yolo26_project/runs_stage1_open/weights/best.pt` (launch: `hand_model_path`)
- 사이드뷰 캘리브레이션 ROI 안에서 손을 감지합니다.
- `hand_auto_confirm_enabled:=false` (기본) — 로비/게임 UI에서 켜면 손 이탈 후 RealSense 자동 수 확인.
- 로봇 이동 중 보드 위 손 감지 시 `chess/hand_in_board` 토픽으로 일시정지 (`hand_safety_enabled`, 기본 ON).

### 절차

1. 사이드 웹캠을 고정한 뒤 빈 보드 또는 기물 배치된 보드를 촬영합니다.
2. 이미지에서 보드 네 모서리 픽셀 좌표를 측정합니다. 순서: **a1 → h1 → h8 → a8**.
3. `board_corners` 배열 `[x1,y1, x2,y2, x3,y3, x4,y4]` 로 저장합니다.
4. 보드가 UI와 반대로 보이면 `board_flipped` 또는 `flip_files`를 조정합니다.
5. launch 재시작 후 UI 사이드바 **Reality Check → 보드 검증** 또는 `POST /api/twin/verify`로 확인합니다.

### 검증

```bash
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python3 -m pytest chess_ws/src/chess_web_ui/test/test_board_twin.py -q
```

실기에서는 RealSense 스캔이 정상인 상태에서 고의로 기물을 옮긴 뒤 mismatch 설명과 추천 FEN이 표시되는지 확인하세요.