"""체스 로봇 하드웨어 통합 (DSR + RealSense 비전 + chess pick&place)."""

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
    default_robot_params = os.path.join(robot_share, 'config', 'robot_params.yaml')
    default_vision_params = os.path.join(vision_share, 'config', 'vision_realsense_params.yaml')

    dsr_launch = os.path.join(robot_share, 'launch', 'cobot_dsr_bringup.launch.py')
    realsense_launch = os.path.join(vision_share, 'launch', 'realsense_camera.launch.py')

    robot_launch = os.path.join(robot_share, 'launch', 'robot.launch.py')

    start_robot_arg = DeclareLaunchArgument('start_robot', default_value='true')
    start_realsense_arg = DeclareLaunchArgument('start_realsense', default_value='true')
    start_vision_arg = DeclareLaunchArgument('start_vision', default_value='true')
    start_pick_place_arg = DeclareLaunchArgument('start_pick_place', default_value='true')
    use_fake_arg = DeclareLaunchArgument('use_fake', default_value='false')
    host_arg = DeclareLaunchArgument('host', default_value='192.168.137.100')
    robot_params_arg = DeclareLaunchArgument('robot_params', default_value=default_robot_params)
    params_overlay_arg = DeclareLaunchArgument('params_overlay', default_value='')
    vision_params_arg = DeclareLaunchArgument('vision_params', default_value=default_vision_params)

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
        condition=IfCondition(LaunchConfiguration('start_realsense')),
    )

    occupancy = Node(
        package='chess_occupancy',
        executable='occupancy_node',
        name='occupancy_node',
        output='screen',
        parameters=[
            LaunchConfiguration('vision_params'),
            # vision_realsense_params.yaml intentionally leaves this blank (see
            # its comment) — resolve it from the installed package share dir so
            # depth-based occupancy doesn't lose its empty-board reference.
            {'empty_depth_reference_path': os.path.join(vision_share, 'config', 'empty_board_depth.npz')},
        ],
        condition=IfCondition(LaunchConfiguration('start_vision')),
    )

    pick_place = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(robot_launch),
        launch_arguments={
            'use_fake': LaunchConfiguration('use_fake'),
            'params_file': LaunchConfiguration('robot_params'),
            'params_overlay': LaunchConfiguration('params_overlay'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('start_pick_place')),
    )

    return LaunchDescription([
        start_robot_arg,
        start_realsense_arg,
        start_vision_arg,
        start_pick_place_arg,
        use_fake_arg,
        host_arg,
        robot_params_arg,
        params_overlay_arg,
        vision_params_arg,
        dsr,
        realsense,
        occupancy,
        pick_place,
    ])
