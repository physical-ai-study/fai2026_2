"""Combine installed UR5e and course CRANE+ V2 models for Gazebo Classic."""

from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

from ament_index_python.packages import get_package_share_directory
import xacro


def build_robot_description(controllers_file):
    """Reuse the course gripper meshes, inertias and joint without the CRANE arm."""
    ur_share = Path(get_package_share_directory('ur_description'))
    crane_share = Path(get_package_share_directory('crane_plus_description'))
    ur = ET.fromstring(xacro.process_file(
        str(ur_share / 'urdf' / 'ur.urdf.xacro'), mappings={
            'name': 'ur5e_with_crane_gripper', 'ur_type': 'ur5e',
            'sim_gazebo': 'true', 'safety_limits': 'true',
            'safety_pos_margin': '0.15',
            'simulation_controllers': str(controllers_file),
            'initial_positions_file': str(ur_share / 'config' / 'initial_positions.yaml'),
        }).toxml())
    # Only extract geometry and one joint. Never start the CRANE hardware/plugin.
    crane = ET.fromstring(xacro.process_file(
        str(crane_share / 'urdf' / 'crane_plus.urdf.xacro'), mappings={
            'use_gazebo': 'false', 'use_camera': 'false',
        }).toxml())
    for name in ('black', 'white'):
        material = deepcopy(crane.find(f"material[@name='{name}']"))
        if material is None:
            raise RuntimeError(f'Course gripper material missing: {name}')
        material.set('name', 'course_gripper_' + name)
        ur.append(material)
    for name in ('crane_plus_link4', 'crane_plus_link_hand'):
        link = deepcopy(crane.find(f"link[@name='{name}']"))
        if link is None:
            raise RuntimeError(f'Course gripper link missing: {name}')
        for material in link.findall('.//material'):
            if material.get('name') in ('black', 'white'):
                material.set('name', 'course_gripper_' + material.get('name'))
        ur.append(link)
    hand = deepcopy(crane.find("joint[@name='crane_plus_joint_hand']"))
    if hand is None:
        raise RuntimeError('Course gripper joint missing: crane_plus_joint_hand')
    ur.append(hand)
    # A simple 20 mm spacer is a simulation adapter, not a manufactured part.
    adapter = ET.fromstring('''<robot>
      <link name="course_gripper_adapter">
        <visual><origin xyz="0 0 0.01"/><geometry>
          <cylinder radius="0.03" length="0.02"/>
        </geometry><material name="course_gripper_black"/></visual>
        <collision><origin xyz="0 0 0.01"/><geometry>
          <cylinder radius="0.03" length="0.02"/>
        </geometry></collision>
        <inertial><origin xyz="0 0 0.01"/><mass value="0.05"/>
          <inertia ixx="0.000012917" ixy="0" ixz="0"
                   iyy="0.000012917" iyz="0" izz="0.0000225"/>
        </inertial>
      </link>
      <joint name="tool0_to_course_gripper_adapter" type="fixed">
        <parent link="tool0"/><child link="course_gripper_adapter"/>
      </joint>
      <joint name="course_gripper_mount" type="fixed">
        <origin xyz="0 0 0.02"/><parent link="course_gripper_adapter"/>
        <child link="crane_plus_link4"/>
      </joint>
    </robot>''')
    for element in adapter:
        ur.append(element)
    for name in ('crane_plus_link4', 'crane_plus_link_hand'):
        gazebo = ET.SubElement(ur, 'gazebo', reference=name)
        ET.SubElement(gazebo, 'mu1').text = '0.2'
        ET.SubElement(gazebo, 'mu2').text = '0.2'
        ET.SubElement(gazebo, 'material').text = (
            'Gazebo/Black' if name == 'crane_plus_link4' else 'Gazebo/White')
    systems = ur.findall('ros2_control')
    if (len(systems) != 1 or systems[0].findtext('hardware/plugin')
            != 'gazebo_ros2_control/GazeboSystem'):
        raise RuntimeError('Expected one UR GazeboSystem; check the Humble UR model version.')
    # One robot, one Gazebo plugin and one controller manager for all seven joints.
    joint = ET.SubElement(systems[0], 'joint', name='crane_plus_joint_hand')
    command = ET.SubElement(joint, 'command_interface', name='position')
    limit = hand.find('limit')
    for bound in ('min', 'max'):
        ET.SubElement(command, 'param', name=bound).text = limit.get(
            'lower' if bound == 'min' else 'upper')
    position = ET.SubElement(joint, 'state_interface', name='position')
    ET.SubElement(position, 'param', name='initial_value').text = '0.0'
    ET.SubElement(joint, 'state_interface', name='velocity')
    ET.SubElement(joint, 'state_interface', name='effort')
    return ET.tostring(ur, encoding='unicode')
