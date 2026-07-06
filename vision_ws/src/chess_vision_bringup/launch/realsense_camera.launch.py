"""cobot2_ws RealSense bringup (rs_align_depth_launch + 동일 파라미터)."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    realsense_share = get_package_share_directory('realsense2_camera')
    align_depth_launch = os.path.join(
        realsense_share,
        'examples',
        'align_depth',
        'rs_align_depth_launch.py',
    )

    serial_no_arg = DeclareLaunchArgument(
        'serial_no',
        default_value="''",
        description='RealSense serial number (empty = first device)',
    )

    realsense_camera = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(align_depth_launch),
        launch_arguments={
            'depth_module.depth_profile': '848x480x30',
            'rgb_camera.color_profile': '1280x720x30',
            'initial_reset': 'true',
            'align_depth.enable': 'true',
            'enable_rgbd': 'true',
            'pointcloud.enable': 'true',
            'serial_no': LaunchConfiguration('serial_no'),
        }.items(),
    )

    return LaunchDescription([
        serial_no_arg,
        realsense_camera,
    ])
