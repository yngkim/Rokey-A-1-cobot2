#!/usr/bin/env bash
# 체스 + cobot 통합 ROS2 환경 (모노레포)
# 사용법: source ~/Rokey-A-1-cobot2/chess_project_env.sh

set -eo pipefail

REPO_ROOT="${CHESS_REPO_ROOT:-${HOME}/Rokey-A-1-cobot2}"

source /opt/ros/humble/setup.bash

for ws in chess_interface_ws vision_ws chess_ws robot_ws; do
  setup="${REPO_ROOT}/${ws}/install/setup.bash"
  if [[ -f "${setup}" ]]; then
    source "${setup}"
  else
    echo "[chess_project_env] skip (not built): ${ws}" >&2
  fi
done

# doosan-robot2 (외부 의존성, 선택)
for ws in cobot_ws; do
  setup="${HOME}/${ws}/install/setup.bash"
  if [[ -f "${setup}" ]]; then
    source "${setup}"
  fi
done

if [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.nvm/nvm.sh"
  nvm use 20 2>/dev/null || nvm use 18 2>/dev/null || true
fi

echo "[chess_project_env] repo: ${REPO_ROOT}"
echo "  node:                 $(node -v 2>/dev/null || echo NOT FOUND)"
echo "  chess_vision_bringup: $(ros2 pkg prefix chess_vision_bringup 2>/dev/null || echo NOT FOUND)"
echo "  chess_robot_bringup:  $(ros2 pkg prefix chess_robot_bringup 2>/dev/null || echo NOT FOUND)"
echo "  robot_control:        $(ros2 pkg prefix robot_control 2>/dev/null || echo NOT FOUND)"
echo "  dsr_bringup2:         $(ros2 pkg prefix dsr_bringup2 2>/dev/null || echo NOT FOUND)"
