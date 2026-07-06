from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
  return LaunchDescription([
      Node(
          package='chess_orchestrator',
          executable='orchestrator_node',
          name='orchestrator_node',
          output='screen',
      ),
      Node(
          package='chess_ui',
          executable='ui_node',
          name='ui_node',
          output='screen',
      ),
      Node(
          package='chess_occupancy',
          executable='fake_vision_node',
          name='fake_vision_node',
          output='screen',
      ),
      Node(
          package='chess_pick_place',
          executable='fake_robot_node',
          name='fake_robot_node',
          output='screen',
      ),
  ])
