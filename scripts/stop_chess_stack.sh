#!/usr/bin/env bash
# Stop stale chess ROS launches and DSR processes before a clean restart.
set -euo pipefail

echo "[stop_chess_stack] sending SIGINT to ros2 launch..."
pkill -INT -f 'ros2 launch chess_web_ui' 2>/dev/null || true
sleep 2
pkill -TERM -f 'ros2 launch chess_web_ui' 2>/dev/null || true
sleep 1
pkill -KILL -f 'ros2 launch chess_web_ui' 2>/dev/null || true

for pattern in \
  'doosan_pick_place_node' \
  'fake_robot_node' \
  'web_bridge' \
  'vision_game_node' \
  'occupancy_node' \
  'ros2_control_node' \
  'realsense2_camera_node' \
  'spawner.*dsr_controller2' \
  'spawner.*joint_state_broadcaster'
do
  pkill -TERM -f "$pattern" 2>/dev/null || true
done
sleep 1

echo "[stop_chess_stack] done. Verify with: ros2 node list | grep pick_place"
