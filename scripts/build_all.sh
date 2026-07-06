#!/usr/bin/env bash
# 모노레포 워크스페이스 순서대로 colcon build
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for ws in chess_interface_ws vision_ws chess_ws robot_ws; do
  echo "=== building ${ws} ==="
  (cd "${REPO_ROOT}/${ws}" && colcon build --symlink-install)
done

echo "=== done. run: source ${REPO_ROOT}/chess_project_env.sh ==="
