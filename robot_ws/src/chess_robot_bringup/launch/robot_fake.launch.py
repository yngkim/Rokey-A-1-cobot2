from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
  return LaunchDescription([
      Node(
          package='chess_pick_place',
          executable='fake_robot_node',
          name='fake_robot_node',
          output='screen',
      ),
  ])
