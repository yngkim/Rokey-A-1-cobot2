# Chess / Hand YOLO weights

런타임에 쓰는 가중치만 보관합니다.

## Twin 사이드뷰 (기물 탐지)

- 경로: `model/weights/chess_final_side1_best.pt`
- launch: `twin_model_path` (기본값 위 경로)

## 손 감지

- 경로: `hand_yolo26_project/runs_stage2_finetune/weights/best.pt`
- launch: `hand_model_path` (기본값 위 경로)
- stage2는 실제 리그 카메라/조명으로 파인튜닝된 가중치입니다.

## 사이드뷰 캘리브레이션

- 설정: `chess_ws/src/chess_web_ui/config/board_twin_side_calibration.json`
- `board_corners` 순서: **a1 → h1 → h8 → a8**
- RealSense 점유가 1차 기준이고, 사이드뷰 YOLO는 참고용입니다.
