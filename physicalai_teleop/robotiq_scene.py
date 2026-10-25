"""Assemble installed UR and Robotiq assets for Gazebo Classic."""

from copy import deepcopy
from io import StringIO
from pathlib import Path
from xml.sax.saxutils import quoteattr
import xml.etree.ElementTree as ET

from ament_index_python.packages import get_package_prefix, get_package_share_directory
import xacro


GRIPPER_COMMAND_JOINT = 'robotiq_85_left_knuckle_joint'

GRIPPER_JOINTS = {
    'robotiq_85_left_knuckle_joint': 1.0,
    'robotiq_85_right_knuckle_joint': -1.0,
    'robotiq_85_left_inner_knuckle_joint': 1.0,
    'robotiq_85_right_inner_knuckle_joint': -1.0,
    'robotiq_85_left_finger_tip_joint': -1.0,
    'robotiq_85_right_finger_tip_joint': 1.0,
}


def build_robotiq_description(controllers_file, grasp_assist=True):
    """Add the 2F-85 geometry to one UR GazeboSystem and controller manager."""
    ur_share = Path(get_package_share_directory('ur_description'))
    gripper_share = Path(get_package_share_directory('robotiq_description'))
    ur = ET.fromstring(xacro.process_file(
        str(ur_share / 'urdf' / 'ur.urdf.xacro'), mappings={
            'name': 'ur5e_robotiq', 'ur_type': 'ur5e',
            'sim_gazebo': 'true', 'safety_limits': 'true',
            'safety_pos_margin': '0.15',
            'simulation_controllers': str(controllers_file),
            'initial_positions_file': str(ur_share / 'config' / 'initial_positions.yaml'),
        }).toxml())
    # The tabletop belongs to the SDF world; remove the UR demo's extra plane.
    for element in list(ur):
        if element.get('name') in ('ground_plane', 'ground_plane_joint'):
            ur.remove(element)
    mount = next((joint for joint in ur.findall('joint')
                  if joint.find('parent') is not None
                  and joint.find('parent').get('link') == 'world'
                  and joint.find('child').get('link') == 'base_link'), None)
    if mount is None:
        raise RuntimeError('Expected the Humble UR world-to-base_link fixed joint.')
    origin = mount.find('origin')
    if origin is None:
        origin = ET.SubElement(mount, 'origin')
    origin.set('xyz', '0 0 0.4')

    macro_file = gripper_share / 'urdf' / 'robotiq_2f_85_macro.urdf.xacro'
    macro_tree = ET.parse(macro_file)
    macro = macro_tree.find("{http://wiki.ros.org/xacro}macro[@name='robotiq_gripper']")
    if macro is None:
        raise RuntimeError('robotiq_description does not contain robotiq_gripper.')
    # Some older Humble descriptions do not expose include_ros2_control.
    # Extract geometry only in either case, so no hardware driver is started.
    geometry_only = (' include_ros2_control="false"'
                     if 'include_ros2_control' in macro.get('params', '') else '')
    wrapper = f'''<robot xmlns:xacro="http://wiki.ros.org/xacro" name="gripper">
      <xacro:include filename={quoteattr(str(macro_file))}/>
      <xacro:robotiq_gripper name="robotiq" prefix="" parent="tool0"{geometry_only}>
        <origin xyz="0 0 0.02" rpy="0 0 0"/>
      </xacro:robotiq_gripper>
    </robot>'''
    doc = xacro.parse(StringIO(wrapper))
    xacro.process_doc(doc)
    gripper = ET.fromstring(doc.toxml())
    for element in gripper:
        if element.tag in ('link', 'joint', 'material'):
            ur.append(deepcopy(element))
    # The small mounting gap is filled by a simple simulation spacer.
    spacer = ET.fromstring('''<robot>
      <link name="robotiq_mount_spacer">
        <visual><origin xyz="0 0 0.01"/><geometry>
          <cylinder radius="0.0315" length="0.02"/></geometry>
          <material name="spacer_grey"><color rgba="0.3 0.3 0.3 1"/></material>
        </visual>
        <collision><origin xyz="0 0 0.01"/><geometry>
          <cylinder radius="0.0315" length="0.02"/></geometry></collision>
        <inertial><origin xyz="0 0 0.01"/><mass value="0.05"/>
          <inertia ixx="0.00001407" ixy="0" ixz="0" iyy="0.00001407"
                   iyz="0" izz="0.00002481"/></inertial>
      </link>
      <joint name="robotiq_mount_spacer_joint" type="fixed">
        <parent link="tool0"/><child link="robotiq_mount_spacer"/>
      </joint>
      <link name="grasp_tcp"/>
      <joint name="grasp_tcp_joint" type="fixed">
        <parent link="robotiq_85_base_link"/><child link="grasp_tcp"/>
        <origin xyz="0 0 0.145"/>
      </joint>
    </robot>''')
    for element in spacer:
        ur.append(element)
    systems = ur.findall('ros2_control')
    if (len(systems) != 1 or systems[0].findtext('hardware/plugin')
            != 'gazebo_ros2_control/GazeboSystem'):
        raise RuntimeError('Expected one UR Gazebo Classic hardware system.')
    for name, sign in GRIPPER_JOINTS.items():
        source = ur.find(f"joint[@name='{name}']")
        if source is None:
            raise RuntimeError(f'Robotiq model joint missing: {name}')
        limit = source.find('limit')
        if limit is None:
            limit = ET.SubElement(source, 'limit')
        # Humble's released model leaves four mimic joints continuous.
        source.set('type', 'revolute')
        limit.set('lower', '0.0' if sign > 0 else '-0.8')
        limit.set('upper', '0.8' if sign > 0 else '0.0')
        limit.set('velocity', '0.5')
        limit.set('effort', '2.0')
        # Gazebo Classic requires explicit mimic parameters in ros2_control;
        # URDF mimic tags alone only synchronize the TF representation.
        joint = ET.SubElement(systems[0], 'joint', name=name)
        if name != GRIPPER_COMMAND_JOINT:
            mimic = source.find('mimic')
            if mimic is None:
                mimic = ET.SubElement(source, 'mimic')
            mimic.set('joint', GRIPPER_COMMAND_JOINT)
            mimic.set('multiplier', str(sign))
            mimic.set('offset', '0.0')
            ET.SubElement(joint, 'param', name='mimic').text = GRIPPER_COMMAND_JOINT
            ET.SubElement(joint, 'param', name='multiplier').text = str(sign)
        ET.SubElement(joint, 'command_interface', name='position')
        position = ET.SubElement(joint, 'state_interface', name='position')
        ET.SubElement(position, 'param', name='initial_value').text = '0.0'
        ET.SubElement(joint, 'state_interface', name='velocity')
        ET.SubElement(joint, 'state_interface', name='effort')
        dynamics = source.find('dynamics')
        if dynamics is None:
            dynamics = ET.SubElement(source, 'dynamics')
        dynamics.set('damping', '0.03')
        dynamics.set('friction', '0.005')
    for name in ('robotiq_85_left_finger_tip_link', 'robotiq_85_right_finger_tip_link'):
        # The upstream mesh has non-URDF surface tags. Use only the Gazebo
        # extension below so there is a single, explicit contact definition.
        for collision in ur.findall(f"link[@name='{name}']/collision"):
            for surface in list(collision.findall('surface')):
                collision.remove(surface)
        gazebo = ET.SubElement(ur, 'gazebo', reference=name)
        for tag, value in {'mu1': '1.5', 'mu2': '1.5', 'kp': '2000',
                           'kd': '20', 'minDepth': '0.0001', 'maxVel': '0.01'}.items():
            ET.SubElement(gazebo, tag).text = value
    if grasp_assist:
        # Otherwise URDF-to-SDF fixed-joint reduction removes the base link
        # used as the attachment reference frame by the model plugin.
        fixed = ET.SubElement(ur, 'gazebo', reference='robotiq_85_base_joint')
        ET.SubElement(fixed, 'preserveFixedJoint').text = 'true'
        plugin_path = Path(get_package_prefix('physicalai_teleop')) / 'lib' / 'libphysicalai_grasp_assist.so'
        if not plugin_path.is_file():
            raise RuntimeError('Grasp assist plugin missing. Rebuild physicalai_teleop.')
        gazebo = ET.SubElement(ur, 'gazebo')
        ET.SubElement(gazebo, 'plugin', name='physicalai_grasp_assist', filename=str(plugin_path))
    # Resolve package mesh URIs to local files; no Gazebo Fuel download needed.
    shares = {}
    for mesh in ur.findall('.//mesh'):
        filename = mesh.get('filename', '')
        if filename.startswith('package://'):
            package, relative = filename[len('package://'):].split('/', 1)
            if package not in shares:
                shares[package] = Path(get_package_share_directory(package))
            mesh.set('filename', 'file://' + str(shares[package] / relative))
    return ET.tostring(ur, encoding='unicode')
