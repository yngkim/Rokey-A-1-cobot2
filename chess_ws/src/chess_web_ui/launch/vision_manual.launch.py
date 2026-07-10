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
    voice_llm_model_arg = DeclareLaunchArgument(
        'voice_llm_model',
        default_value='qwen2.5:7b',
        description='Ollama model for natural-language voice moves',
    )
    voice_llm_enabled_arg = DeclareLaunchArgument(
        'voice_llm_enabled',
        default_value='false',
        description='Always use LLM for voice parse (auto still probes Ollama when false)',
    )
    voice_llm_auto_arg = DeclareLaunchArgument(
        'voice_llm_auto',
        default_value='true',
        description='Use Ollama when available after rule/semantic parse fails',
    )
    voice_llm_base_url_arg = DeclareLaunchArgument(
        'voice_llm_base_url',
        default_value='http://127.0.0.1:11434',
    )
    twin_enabled_arg = DeclareLaunchArgument('twin_enabled', default_value='false')
    twin_webcam_device_arg = DeclareLaunchArgument('twin_webcam_device', default_value='10')
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
    _default_side_model = os.path.join(_repo_root, 'model', 'weights', 'chess_final_side1_best.pt')
    twin_model_path_arg = DeclareLaunchArgument(
        'twin_model_path',
        default_value=_default_side_model,
    )
    twin_calibration_path_arg = DeclareLaunchArgument('twin_calibration_path', default_value='')
    hand_enabled_arg = DeclareLaunchArgument('hand_enabled', default_value='true')
    _default_hand_model = os.path.join(
        _repo_root,
        'hand_yolo26_project',
        'runs_stage1_open',
        'weights',
        'best.pt',
    )
    hand_model_path_arg = DeclareLaunchArgument('hand_model_path', default_value=_default_hand_model)
    hand_auto_confirm_enabled_arg = DeclareLaunchArgument(
        'hand_auto_confirm_enabled',
        default_value='true',
    )
    hand_gone_confirm_delay_sec_arg = DeclareLaunchArgument(
        'hand_gone_confirm_delay_sec',
        default_value='0.35',
    )
    hand_absent_frames_arg = DeclareLaunchArgument('hand_absent_frames', default_value='4')
    hand_confirm_cooldown_sec_arg = DeclareLaunchArgument(
        'hand_confirm_cooldown_sec',
        default_value='1.0',
    )
    auto_detect_moves_arg = DeclareLaunchArgument('auto_detect_moves', default_value='true')
    auto_detect_stable_frames_arg = DeclareLaunchArgument(
        'auto_detect_stable_frames',
        default_value='4',
    )

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
            'auto_detect_moves': LaunchConfiguration('auto_detect_moves'),
            'auto_detect_stable_frames': LaunchConfiguration('auto_detect_stable_frames'),
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
            'voice_llm_enabled': LaunchConfiguration('voice_llm_enabled'),
            'voice_llm_auto': LaunchConfiguration('voice_llm_auto'),
            'voice_llm_model': LaunchConfiguration('voice_llm_model'),
            'voice_llm_base_url': LaunchConfiguration('voice_llm_base_url'),
            'twin_enabled': LaunchConfiguration('twin_enabled'),
            'twin_webcam_device': LaunchConfiguration('twin_webcam_device'),
            'twin_model_path': LaunchConfiguration('twin_model_path'),
            'twin_calibration_path': LaunchConfiguration('twin_calibration_path'),
            'hand_enabled': LaunchConfiguration('hand_enabled'),
            'hand_model_path': LaunchConfiguration('hand_model_path'),
            'hand_auto_confirm_enabled': LaunchConfiguration('hand_auto_confirm_enabled'),
            'hand_gone_confirm_delay_sec': LaunchConfiguration('hand_gone_confirm_delay_sec'),
            'hand_absent_frames': LaunchConfiguration('hand_absent_frames'),
            'hand_confirm_cooldown_sec': LaunchConfiguration('hand_confirm_cooldown_sec'),
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
        voice_llm_model_arg,
        voice_llm_enabled_arg,
        voice_llm_auto_arg,
        voice_llm_base_url_arg,
        twin_enabled_arg,
        twin_webcam_device_arg,
        twin_model_path_arg,
        twin_calibration_path_arg,
        hand_enabled_arg,
        hand_model_path_arg,
        hand_auto_confirm_enabled_arg,
        hand_gone_confirm_delay_sec_arg,
        hand_absent_frames_arg,
        hand_confirm_cooldown_sec_arg,
        auto_detect_moves_arg,
        auto_detect_stable_frames_arg,
        hardware,
        vision_game,
        web_bridge,
    ])
