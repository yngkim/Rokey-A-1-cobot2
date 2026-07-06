"""RealSense 탑뷰 비전 (cobot2_ws 카메라 bringup + occupancy scan)."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_share = get_package_share_directory('chess_vision_bringup')
    default_params = os.path.join(pkg_share, 'config', 'vision_realsense_params.yaml')
    realsense_launch = os.path.join(pkg_share, 'launch', 'realsense_camera.launch.py')

    params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params,
        description='Vision parameter YAML file for RealSense top view',
    )
    start_realsense_arg = DeclareLaunchArgument(
        'start_realsense',
        default_value='true',
        description='Launch cobot2_ws-style RealSense driver',
    )
    serial_no_arg = DeclareLaunchArgument(
        'serial_no',
        default_value="''",
        description='RealSense serial number (empty = first device)',
    )

    realsense_camera = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(realsense_launch),
        launch_arguments={
            'serial_no': LaunchConfiguration('serial_no'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('start_realsense')),
    )

    return LaunchDescription([
        params_file_arg,
        start_realsense_arg,
        serial_no_arg,
        realsense_camera,
        Node(
            package='chess_occupancy',
            executable='occupancy_node',
            name='occupancy_node',
            output='screen',
            parameters=[LaunchConfiguration('params_file')],
        ),
    ])
