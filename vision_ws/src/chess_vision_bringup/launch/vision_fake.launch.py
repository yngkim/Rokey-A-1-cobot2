from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
  return LaunchDescription([
      Node(
          package='chess_occupancy',
          executable='fake_vision_node',
          name='fake_vision_node',
          output='screen',
      ),
  ])
