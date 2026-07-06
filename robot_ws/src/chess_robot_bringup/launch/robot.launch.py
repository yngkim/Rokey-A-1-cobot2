from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def _launch_setup(context, *args, **kwargs):
    pkg_share = get_package_share_directory('chess_robot_bringup')
    default_params = os.path.join(pkg_share, 'config', 'robot_params.yaml')
    params_file = LaunchConfiguration('params_file').perform(context) or default_params
    overlay = LaunchConfiguration('params_overlay').perform(context)
    param_files = [params_file]
    if overlay:
        param_files.append(overlay)

    use_fake = LaunchConfiguration('use_fake')

    fake_node = Node(
        package='chess_pick_place',
        executable='fake_robot_node',
        name='pick_place_node',
        output='screen',
        parameters=param_files,
        condition=IfCondition(use_fake),
    )

    real_node = Node(
        package='chess_pick_place',
        executable='doosan_pick_place_node',
        name='pick_place_node',
        output='screen',
        parameters=param_files,
        condition=UnlessCondition(use_fake),
    )
    return [fake_node, real_node]


def generate_launch_description():
    pkg_share = get_package_share_directory('chess_robot_bringup')
    default_params = os.path.join(pkg_share, 'config', 'robot_params.yaml')

    use_fake_arg = DeclareLaunchArgument(
        'use_fake',
        default_value='true',
        description='Use fake robot node instead of Doosan hardware',
    )
    params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params,
        description='Robot calibration parameters',
    )
    params_overlay_arg = DeclareLaunchArgument(
        'params_overlay',
        default_value='',
        description='Optional second YAML overlay (e.g. vision_manual_robot_params.yaml)',
    )

    return LaunchDescription([
        use_fake_arg,
        params_file_arg,
        params_overlay_arg,
        OpaqueFunction(function=_launch_setup),
    ])
