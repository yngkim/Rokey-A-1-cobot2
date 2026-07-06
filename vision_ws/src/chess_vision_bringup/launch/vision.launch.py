from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_share = get_package_share_directory('chess_vision_bringup')
    default_params = os.path.join(pkg_share, 'config', 'vision_params.yaml')

    params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params,
        description='Vision parameter YAML file',
    )

    return LaunchDescription([
        params_file_arg,
        Node(
            package='chess_occupancy',
            executable='occupancy_node',
            name='occupancy_node',
            output='screen',
            parameters=[LaunchConfiguration('params_file')],
        ),
        Node(
            package='chess_piece_classifier',
            executable='piece_classifier_node',
            name='piece_classifier_node',
            output='screen',
            parameters=[LaunchConfiguration('params_file')],
        ),
    ])
