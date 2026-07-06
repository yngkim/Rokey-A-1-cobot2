"""cobot2_ws pick&place 스택 (RealSense + detection + robot_control)."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    robot_share = get_package_share_directory('chess_robot_bringup')
    vision_share = get_package_share_directory('chess_vision_bringup')

    dsr_launch = os.path.join(robot_share, 'launch', 'cobot_dsr_bringup.launch.py')
    realsense_launch = os.path.join(vision_share, 'launch', 'realsense_camera.launch.py')

    start_robot_arg = DeclareLaunchArgument('start_robot', default_value='true')
    start_realsense_arg = DeclareLaunchArgument('start_realsense', default_value='true')
    start_detection_arg = DeclareLaunchArgument('start_detection', default_value='true')
    start_robot_control_arg = DeclareLaunchArgument('start_robot_control', default_value='false')
    host_arg = DeclareLaunchArgument('host', default_value='192.168.137.100')
    serial_no_arg = DeclareLaunchArgument('serial_no', default_value="''")

    dsr = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(dsr_launch),
        launch_arguments={
            'start_robot': LaunchConfiguration('start_robot'),
            'host': LaunchConfiguration('host'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('start_robot')),
    )

    realsense = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(realsense_launch),
        launch_arguments={
            'serial_no': LaunchConfiguration('serial_no'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('start_realsense')),
    )

    detection = Node(
        package='object_detection',
        executable='object_detection',
        name='object_detection',
        output='screen',
        condition=IfCondition(LaunchConfiguration('start_detection')),
    )

    robot_control = Node(
        package='robot_control',
        executable='robot_control',
        name='robot_control',
        output='screen',
        condition=IfCondition(LaunchConfiguration('start_robot_control')),
    )

    return LaunchDescription([
        start_robot_arg,
        start_realsense_arg,
        start_detection_arg,
        start_robot_control_arg,
        host_arg,
        serial_no_arg,
        dsr,
        realsense,
        detection,
        robot_control,
    ])
