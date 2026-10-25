"""Start the official Humble UR5e Gazebo Classic model and controller."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    """Keep keyboard teleop in a separate interactive terminal."""
    simulation = os.path.join(
        get_package_share_directory('ur_simulation_gazebo'),
        'launch', 'ur_sim_control.launch.py')
    return LaunchDescription([
        DeclareLaunchArgument('launch_rviz', default_value='true'),
        DeclareLaunchArgument('gazebo_gui', default_value='true'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(simulation),
            launch_arguments={
                'ur_type': 'ur5e',
                'initial_joint_controller': 'joint_trajectory_controller',
                'launch_rviz': LaunchConfiguration('launch_rviz'),
                'gazebo_gui': LaunchConfiguration('gazebo_gui'),
            }.items()),
    ])
