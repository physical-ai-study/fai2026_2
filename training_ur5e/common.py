"""Joint order and features shared by conversion, training and inference."""
import math
from pathlib import Path
import yaml

ARM = ['shoulder_pan_joint', 'shoulder_lift_joint', 'elbow_joint',
       'wrist_1_joint', 'wrist_2_joint', 'wrist_3_joint']
GRIPPER = 'robotiq_85_left_knuckle_joint'
JOINTS = ARM + [GRIPPER]
ARM_TOPIC = '/joint_trajectory_controller/joint_trajectory'
GRIP_TOPIC = '/robotiq_gripper_controller/joint_trajectory'
LOWER = [-math.tau + .15, -math.tau + .15, -math.pi + .15,
         -math.tau + .15, -math.tau + .15, -math.tau + .15, -.01]
UPPER = [-x for x in LOWER[:6]] + [.81]
FEATURES = {key: {'dtype': 'float32', 'shape': (7,), 'names': JOINTS[:]}
            for key in ('observation.state', 'observation.environment_state', 'action')}


def load_config(path=None):
    path = Path(path) if path else Path(__file__).with_name('config.yaml')
    with path.open() as stream:
        return yaml.safe_load(stream)


def ordered(names, positions, wanted):
    if len(names) != len(positions) or len(set(names)) != len(names):
        raise ValueError('Malformed or duplicate joint names.')
    values = dict(zip(names, positions))
    result = [float(values[name]) for name in wanted]
    if not all(math.isfinite(x) for x in result):
        raise ValueError('Non-finite joint value.')
    return result


def valid_state(values):
    return len(values) == 7 and all(
        math.isfinite(x) and lo <= x <= hi
        for x, lo, hi in zip(values, LOWER, UPPER))
