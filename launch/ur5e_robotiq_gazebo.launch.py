"""Launch UR5e, Robotiq 2F-85 and a 20 cm practice cylinder at fingertip height."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument, EmitEvent, IncludeLaunchDescription,
    OpaqueFunction, RegisterEventHandler,
)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from physicalai_teleop.robotiq_scene import build_robotiq_description


def launch_setup(context):
    """Create the combined description using installed model assets."""
    share = get_package_share_directory('physicalai_teleop')
    controllers = os.path.join(share, 'config', 'ur5e_robotiq_controllers.yaml')
    assist = LaunchConfiguration('grasp_assist').perform(context).lower() == 'true'
    description = build_robotiq_description(controllers, grasp_assist=assist)
    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('gazebo_ros'), 'launch', 'gazebo.launch.py')),
        launch_arguments={
            'world': os.path.join(share, 'worlds', 'ur5e_pick.world'),
            'gui': LaunchConfiguration('gazebo_gui'),
            'verbose': 'false',
        }.items())
    state_publisher = Node(
        package='robot_state_publisher', executable='robot_state_publisher',
        output='screen', parameters=[{
            'robot_description': ParameterValue(description, value_type=str),
            'use_sim_time': True,
        }])
    spawn = Node(
        package='gazebo_ros', executable='spawn_entity.py', output='screen',
        arguments=['-entity', 'ur5e_robotiq', '-topic', 'robot_description',
                   '-timeout', '120'])
    controllers_node = Node(
        package='controller_manager', executable='spawner', output='screen',
        arguments=['joint_state_broadcaster', 'joint_trajectory_controller',
                   'robotiq_gripper_controller', '-c', '/controller_manager',
                   '--controller-manager-timeout', '120'])

    def after_spawn(event, launch_context):
        if event.returncode != 0:
            return [EmitEvent(event=Shutdown(reason='UR5e model creation failed.'))]
        return [controllers_node]

    rviz = Node(
        package='rviz2', executable='rviz2', output='log',
        condition=IfCondition(LaunchConfiguration('launch_rviz')),
        arguments=['-d', os.path.join(get_package_share_directory('ur_description'),
                                    'rviz', 'view_robot.rviz')],
        parameters=[{'use_sim_time': True}])
    return [gazebo, state_publisher,
            RegisterEventHandler(OnProcessExit(target_action=spawn, on_exit=after_spawn)),
            spawn, rviz]


def generate_launch_description():
    """Keep the keyboard program in its own interactive terminal."""
    return LaunchDescription([
        DeclareLaunchArgument('gazebo_gui', default_value='true'),
        DeclareLaunchArgument('launch_rviz', default_value='true'),
        DeclareLaunchArgument('grasp_assist', default_value='true'),
        OpaqueFunction(function=launch_setup),
    ])
