"""Doosan M0609 bringup (cobot_ws / cobot2_ws 패턴)."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    dsr_share = get_package_share_directory('dsr_bringup2')
    dsr_launch = os.path.join(dsr_share, 'launch', 'dsr_bringup2_rviz.launch.py')

    mode_arg = DeclareLaunchArgument('mode', default_value='real')
    host_arg = DeclareLaunchArgument('host', default_value='192.168.137.100')
    port_arg = DeclareLaunchArgument('port', default_value='12345')
    model_arg = DeclareLaunchArgument('model', default_value='m0609')
    name_arg = DeclareLaunchArgument('name', default_value='dsr01')
    start_arg = DeclareLaunchArgument('start_robot', default_value='true')

    dsr_bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(dsr_launch),
        launch_arguments={
            'mode': LaunchConfiguration('mode'),
            'host': LaunchConfiguration('host'),
            'port': LaunchConfiguration('port'),
            'model': LaunchConfiguration('model'),
            'name': LaunchConfiguration('name'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('start_robot')),
    )

    return LaunchDescription([
        mode_arg,
        host_arg,
        port_arg,
        model_arg,
        name_arg,
        start_arg,
        dsr_bringup,
    ])
