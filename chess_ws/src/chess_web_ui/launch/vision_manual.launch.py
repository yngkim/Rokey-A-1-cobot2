#!/usr/bin/env python3
"""Vision manual mode: robot hardware + vision game node + web bridge."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    robot_share = get_package_share_directory('chess_robot_bringup')
    robot_hardware_launch = os.path.join(robot_share, 'launch', 'robot_hardware.launch.py')
    vision_manual_params = os.path.join(robot_share, 'config', 'vision_manual_robot_params.yaml')

    use_fake_arg = DeclareLaunchArgument('use_fake', default_value='false')
    host_arg = DeclareLaunchArgument('host', default_value='192.168.137.100')
    http_port_arg = DeclareLaunchArgument('http_port', default_value='8080')
    human_color_arg = DeclareLaunchArgument('human_color', default_value='white')
    auto_bot_move_arg = DeclareLaunchArgument('auto_bot_move', default_value='true')
    engine_depth_arg = DeclareLaunchArgument('engine_depth', default_value='8')
    difficulty_arg = DeclareLaunchArgument('difficulty', default_value='medium')

    hardware = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(robot_hardware_launch),
        launch_arguments={
            'use_fake': LaunchConfiguration('use_fake'),
            'host': LaunchConfiguration('host'),
            'params_overlay': vision_manual_params,
        }.items(),
    )

    vision_game = Node(
        package='chess_web_ui',
        executable='vision_game_node',
        name='vision_game_node',
        output='screen',
        parameters=[{
            'auto_detect_moves': False,
        }],
    )

    web_bridge = Node(
        package='chess_web_ui',
        executable='web_bridge',
        name='chess_web_bridge',
        output='screen',
        parameters=[{
            'http_port': LaunchConfiguration('http_port'),
            'vision_mode': True,
            'human_color': LaunchConfiguration('human_color'),
            'auto_bot_move': LaunchConfiguration('auto_bot_move'),
            'engine_depth': LaunchConfiguration('engine_depth'),
            'difficulty': LaunchConfiguration('difficulty'),
        }],
    )

    return LaunchDescription([
        use_fake_arg,
        host_arg,
        http_port_arg,
        human_color_arg,
        auto_bot_move_arg,
        engine_depth_arg,
        difficulty_arg,
        hardware,
        vision_game,
        web_bridge,
    ])
