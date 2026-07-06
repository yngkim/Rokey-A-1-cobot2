# Rokey-A-1-cobot2

ROS2 기반 **체스 비전 + Stockfish 엔진 + Doosan cobot** 통합 프로젝트 모노레포.

## 저장소 구조

```
Rokey-A-1-cobot2/
├── chess_interface_ws/src/chess_msgs/       # 공통 메시지
├── vision_ws/src/                           # 보드 검출, 점유, 기물 분류
├── chess_ws/src/                            # 게임 로직, 엔진, 웹 UI
├── robot_ws/src/                            # pick-place, 로봇 bringup
├── scripts/                                 # 빌드·외부 의존성 스크립트
└── chess_project_env.sh                     # 통합 환경 source
```

## 사전 요구사항

- Ubuntu 22.04 + ROS2 Humble
- Node.js 18+ (nvm 권장)
- Stockfish (`sudo apt install stockfish`)
- Intel RealSense (실기 비전)
- Doosan cobot + `doosan-robot2` (별도 설치, 아래 참고)

## 설치

```bash
git clone https://github.com/yngkim/Rokey-A-1-cobot2.git ~/Rokey-A-1-cobot2
cd ~/Rokey-A-1-cobot2

# doosan-robot2 (Git 미포함, ~450MB)
bash scripts/setup_doosan.sh
cd ~/cobot_ws && colcon build --symlink-install

# 모노레포 패키지 빌드
bash scripts/build_all.sh

# 프론트엔드
cd chess_ws/src/chess_web_ui/frontend && npm install
```

## 환경 활성화

```bash
source ~/Rokey-A-1-cobot2/chess_project_env.sh
```

기존 `~/chess_ws` 등 분리 워크스페이스 대신 **이 저장소 경로**를 사용합니다.

## 실행 (비전 + 봇 대국)

```bash
source ~/Rokey-A-1-cobot2/chess_project_env.sh

# T1: DSR bringup (실기)
ros2 launch chess_robot_bringup cobot_dsr_bringup.launch.py host:=192.168.137.100

# T2: 비전 + 로봇 + web_bridge
ros2 launch chess_web_ui vision_manual.launch.py use_fake:=false

# T3: React UI
cd ~/Rokey-A-1-cobot2/chess_ws/src/chess_web_ui/frontend && npm run dev
```

Fake 테스트 (카메라/로봇 stub):

```bash
ros2 launch chess_web_ui vision_manual.launch.py use_fake:=true
```

## 워크스페이스별 패키지

| 워크스페이스 | 패키지 |
|-------------|--------|
| chess_interface_ws | chess_msgs |
| vision_ws | chess_board_detector, chess_occupancy, chess_piece_classifier, chess_vision_bringup |
| chess_ws | chess_game, chess_engine, chess_web_ui, chess_coach, chess_dialogue, chess_orchestrator, chess_ui |
| robot_ws | chess_pick_place, chess_robot_bringup, chess_robot_motion, cobot2_ws |

## Git에 포함하지 않는 항목

- `build/`, `install/`, `log/` (colcon 산출물)
- `frontend/node_modules/`
- `doosan-robot2` (외부 vendor — `scripts/setup_doosan.sh`로 설치)

## 기존 분리 워크스페이스에서 이전한 경우

이전에 `~/chess_interface_ws`, `~/vision_ws`, `~/chess_ws`, `~/robot_ws`에서 개발했다면,
이 모노레포로 개발 경로를 옮기거나 `CHESS_REPO_ROOT` 환경 변수로 루트를 지정할 수 있습니다.

```bash
export CHESS_REPO_ROOT=~/Rokey-A-1-cobot2
source ~/Rokey-A-1-cobot2/chess_project_env.sh
```

자세한 UI·게임 흐름은 `chess_ws/src/chess_web_ui/README.md`를 참고하세요.
