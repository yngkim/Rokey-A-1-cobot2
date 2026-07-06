#!/usr/bin/env bash
# doosan-robot2 외부 의존성 설치 (Git에는 포함하지 않음)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOOSAN_SRC="${REPO_ROOT}/robot_ws/src/doosan-robot2"
COBOT_WS="${HOME}/cobot_ws"

if [[ -d "${DOOSAN_SRC}/.git" ]] || [[ -f "${DOOSAN_SRC}/package.xml" ]]; then
  echo "[setup_doosan] already present: ${DOOSAN_SRC}"
  exit 0
fi

mkdir -p "${COBOT_WS}/src"
if [[ ! -d "${COBOT_WS}/src/doosan-robot2" ]]; then
  echo "[setup_doosan] cloning doosan-robot2 into ${COBOT_WS}/src ..."
  git clone https://github.com/DoosanRobotics/doosan-robot2.git "${COBOT_WS}/src/doosan-robot2"
fi

ln -sfn "${COBOT_WS}/src/doosan-robot2" "${DOOSAN_SRC}"
echo "[setup_doosan] linked ${DOOSAN_SRC} -> ${COBOT_WS}/src/doosan-robot2"
echo "[setup_doosan] build: cd ${COBOT_WS} && colcon build"
