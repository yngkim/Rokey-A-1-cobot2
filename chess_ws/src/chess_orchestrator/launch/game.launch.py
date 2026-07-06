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
  ])
