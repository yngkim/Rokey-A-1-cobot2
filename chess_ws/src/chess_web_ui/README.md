# chess_web_ui

React 테스트 UI + HTTP ROS bridge (수동 pick-place / 비전 기반 사용자 수 감지).

## Node.js

Ubuntu 기본 `apt install nodejs`는 **v12**입니다 (Jammy universe 패키지).  
프로젝트는 **nvm + Node 20**을 사용합니다.

```bash
source ~/chess_project_env.sh   # nvm node 20 자동 활성화
node -v                         # v20.20.2
```

## 비전 + 봇 대국 모드 (탑뷰 RealSense + Stockfish + 로봇 자동 수)

### 흐름

1. 웹 UI에서 **내 색(백/흑)** 선택
2. **Reset** — 로봇 홈(observe) + 초기 occupancy 스캔
3. 내 차례: 물리 보드에서 수 → 손을 떼고 **수 두었음** 클릭 → 탑뷰 스캔·감지
4. 로봇 차례: Stockfish가 수 계산 → UI 그리드 즉시 반영 → 로봇 자동 pick-place
5. 한 수씩 교대 반복

**내가 흑**을 선택하면 Reset 후 로봇이 백으로 선수를 둡니다.

### 실행

```bash
source ~/chess_project_env.sh

# T1: DSR bringup (실기)
ros2 launch chess_robot_bringup cobot_dsr_bringup.launch.py host:=192.168.137.100
# T2: set_robot_mode 1

# T3: 비전 + 로봇 + vision_game + web_bridge
ros2 launch chess_web_ui vision_manual.launch.py use_fake:=false

# T4: React UI
cd ~/chess_ws/src/chess_web_ui/frontend && npm run dev
```

Launch 파라미터 (선택):

```bash
ros2 launch chess_web_ui vision_manual.launch.py \
  use_fake:=false human_color:=white auto_bot_move:=true engine_depth:=8
```

Stockfish (선택, 없으면 첫 합법 수 fallback):

```bash
sudo apt install stockfish
```

Fake 테스트 (카메라/로봇 stub):

```bash
ros2 launch chess_web_ui vision_manual.launch.py use_fake:=true
```

### 시험 시나리오

**A — 내가 백**

1. UI: 내가 백 → **Reset**
2. e2→e4 수동 → 2초 후 왼쪽 보드·카메라 occupied 일치 확인
3. 로봇 자동 응수 → UI FEN·실물 보드 일치 확인
4. 2~3 반복

**B — 내가 흑**

1. UI: 내가 흑 → **Reset** → 로봇이 백 선수 자동
2. 로봇 수 후 내가 응수 → 반복

### 검증 체크리스트

- [ ] 내 수 후 UI FEN + 카메라 occupied 일치
- [ ] 로봇 수 후 UI FEN + 실물 보드 일치
- [ ] 내가 흑: Reset 직후 로봇 선수
- [ ] 로봇 차례에 **수 두었음** 비활성
- [ ] 캡처 수 시 로봇 pick 동작

### 알려진 제한

- 프로모션(폰 승급) 미지원
- 캐슬링/앙파상은 occupancy diff 한계 — 오프닝·단순 이동 위주로 시험

### 캘리브레이션

**observe 홈 관절각** (`robot_params.yaml`의 `home_joints`):

```yaml
home_joints: [-12.68, 22.54, 36.06, -0.05, 121.43, -12.17]
```

- Reset / `move_to_observe` / 수 실행 후 복귀 시 모두 이 자세로 이동합니다.
- teach pendant로 체스판 8×8 전체가 탑뷰에 보이는 자세를 측정해 위 값과 일치하는지 확인하세요.

**보드 코너 (`board_manual_corners`) — observe 자세에서 필수**

새 observe 자세에서는 기물이 있는 상태에서 **자동 코너 검출이 거의 실패**합니다. 워핑·역투영·occupancy 모두 4코너 homography가 필요하므로 수동 설정이 필요합니다.

1. `ros2 launch chess_web_ui vision_manual.launch.py use_fake:=false` 실행
2. 웹 UI 오른쪽 **탑뷰 카메라** 패널(또는 `rqt_image_view /vision/debug/top_view`)에서 체스판 테두리 확인
3. ROS를 종료한 뒤, 저장된 프레임 또는 `realsense-viewer`로 **TL → TR → BR → BL** 순서로 픽셀 좌표 측정
4. `vision_ws/src/chess_vision_bringup/config/vision_realsense_params.yaml`에 설정:

   ```yaml
   board_manual_corners: [tl_x, tl_y, tr_x, tr_y, br_x, br_y, bl_x, bl_y]
   ```

   또는 CLI로 측정:

   ```bash
   # ROS 실행 중 프레임 저장 후
   ros2 run chess_board_detector calibrate_corners --image /tmp/frame.jpg
   ```

5. vision 스택 재시작 후 웹 미리보기에서 **노란 보드 ROI** + **파란 격자 64점** 확인
6. **초록 박스**(역투영 polygon)가 기물 실루엣에 맞는지 확인 — 어긋나면 코너 좌표를 미세 조정

**YOLO / 워핑** (`vision_realsense_params.yaml`):

| 파라미터 | 권장 시작값 | 설명 |
|----------|-------------|------|
| `yolo_conf` | 0.13 | 낮출수록 흰 기물 recall 증가 (오탐도 증가) |
| `yolo_multi_pass` | true | 원본+대비+흰기물부스트 4회 추론 후 병합 |
| `heuristic_fallback` | true | YOLO miss 칸을 에지 휴리스틱으로 보완 |
| `yolo_iou` | 0.50 | 겹친 박스 병합 |
| `yolo_imgsz` | 960 | warped 보드에서 해상도 |
| `yolo_warp_board` | true | 보드를 정사각형으로 펼쳐 YOLO 실행 |
| `warp_board_size` | 960 | 칸당 픽셀 증가 → 작은 기물에 유리 |

미리보기는 **원본 카메라 영상**에 YOLO bbox 4코너를 homography로 **역투영**해 그립니다. 코너 캘리브가 맞지 않으면 박스가 기물과 어긋납니다.

### API

- `GET /api/board` — FEN + occupancy + 차례/봇 상태
- `POST /api/game/config` — `{"human_color":"white"|"black"}`
- `GET /api/camera/stream` — MJPEG 탑뷰
- `GET /api/camera/preview.jpg` — 최신 프레임 JPEG 스냅샷
- `POST /api/reset` — 리셋 + 초기 스캔 (+ 로봇 선수 시 자동 첫 수)
- `POST /api/player-moved` — 사용자 수 감지 (비전 스캔)
- `POST /api/move` — 로봇 pick-place (`{"from":"e2","to":"e4"}`) — 디버그용

## 수동 pick-place만 (비전 없음)

```bash
ros2 launch chess_robot_bringup robot.launch.py use_fake:=true
ros2 run chess_web_ui web_bridge --ros-args -p vision_mode:=false
```

## 문제 해결

**8080 포트 / 카메라 안 보임**

구버전 `web_bridge`가 8080을 점유하면 `/api/camera/preview.jpg`가 404입니다.

```bash
fuser -k 8080/tcp
# vision_manual launch 하나만 사용 (web_bridge 포함)
ros2 launch chess_web_ui vision_manual.launch.py use_fake:=false
```

브라우저에서 직접 확인: http://localhost:8080/api/camera/preview.jpg

**DSR `g_node is None`** — `cobot_dsr_bringup`을 pick_place보다 **먼저** 실행.

**보드 상태가 두 곳에서 publish** — `vision_manual` launch는 `publish_board_state: false` 오버레이 사용.
