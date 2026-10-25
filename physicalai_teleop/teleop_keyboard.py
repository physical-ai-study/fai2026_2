#!/usr/bin/env python3
"""Keyboard joint teleoperation for a UR5e in Gazebo Classic / ROS 2 Humble."""

import math
import select
import sys
import termios
import time
import tty

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from rosgraph_msgs.msg import Clock
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from physicalai_teleop.robotiq_scene import GRIPPER_COMMAND_JOINT


ARM_JOINT_NAMES = [
    'shoulder_pan_joint', 'shoulder_lift_joint', 'elbow_joint',
    'wrist_1_joint', 'wrist_2_joint', 'wrist_3_joint',
]
# Match the nominal ur_description limits with the default 0.15 rad margin.
UPPER_LIMITS = [math.tau - 0.15] * 6
UPPER_LIMITS[2] = math.pi - 0.15

HELP = """
UR5e joint teleop (Gazebo simulation):
Q/E:   Select joint (1-6)
W/S:   + / - selected joint
R/F:   + / - all six joints (coarse)
O/C:   Open / close the Robotiq 2F-85 (when enabled)
X:     Return the arm to the configured startup pose (gripper unchanged)
SPACE: Pause / resume publishing from measured joint positions
ESC:   Quit (does not cancel an already submitted trajectory)
No commands are sent until a motion key or a gripper key is pressed.
"""


class KeyboardInput:
    """Temporarily put an interactive Linux terminal in cbreak mode."""

    def __enter__(self):
        """Save the terminal settings before reading individual keys."""
        if not sys.stdin.isatty():
            raise RuntimeError('Run teleop in an interactive container terminal.')
        self.fd = sys.stdin.fileno()
        self.old_settings = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, exc_type, value, traceback):
        """Restore the terminal even when the node is interrupted."""
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)

    def get_key(self):
        """Return one pending key without blocking ROS callbacks."""
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None


class TeleopNode(Node):
    """Publish bounded joint targets after receiving complete joint feedback."""

    def __init__(self):
        """Load robot parameters and wait for feedback before allowing motion."""
        super().__init__('ur5e_joint_teleop')
        defaults = {
            'joint_names': ARM_JOINT_NAMES,
            'joint_lower_limits': [-value for value in UPPER_LIMITS],
            'joint_upper_limits': UPPER_LIMITS,
            'arm_controller_topic': '/joint_trajectory_controller/joint_trajectory',
            'joint_states_topic': '/joint_states',
            'arm_step': 0.025,
            'coarse_step': 0.05,
            'trajectory_duration': 1.0,
            'publish_rate': 20.0,
            'state_timeout': 0.5,
            'max_target_offset': 0.2,
            'home_positions': [0.0, -1.57, 0.0, -1.57, 0.0, 0.0],
            'gripper_enabled': False,
            'gripper_controller_topic': '/robotiq_gripper_controller/joint_trajectory',
            'gripper_open': 0.0,
            'gripper_close': 0.75,
            'gripper_duration': 2.0,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        params = {name: self.get_parameter(name).value for name in defaults}
        self.joint_names = list(params['joint_names'])
        self.lower = list(params['joint_lower_limits'])
        self.upper = list(params['joint_upper_limits'])
        count = len(self.joint_names)
        if (count != 6 or len(set(self.joint_names)) != count
                or not all(self.joint_names)
                or len(self.lower) != count or len(self.upper) != count):
            raise ValueError('Provide six unique joint names and six limit pairs.')
        if not all(math.isfinite(lo) and math.isfinite(hi) and lo < hi
                   for lo, hi in zip(self.lower, self.upper)):
            raise ValueError('Joint limits must be finite and lower < upper.')
        for name in ('arm_step', 'coarse_step', 'trajectory_duration',
                     'publish_rate', 'state_timeout', 'max_target_offset'):
            value = params[name]
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive.')
        self.arm_step = params['arm_step']
        self.coarse_step = params['coarse_step']
        self.duration_ns = round(params['trajectory_duration'] * 1_000_000_000)
        if self.duration_ns < 1 or self.duration_ns // 1_000_000_000 > 2147483647:
            raise ValueError('trajectory_duration is outside the ROS Duration range.')
        self.state_timeout = params['state_timeout']
        self.max_offset = params['max_target_offset']
        self.home = list(params['home_positions'])
        if (len(self.home) != count or not all(
                math.isfinite(value) and lo <= value <= hi
                for value, lo, hi in zip(self.home, self.lower, self.upper))):
            raise ValueError('home_positions must contain six in-range joint angles.')
        self.homing = False
        self.gripper_enabled = params['gripper_enabled']
        self.gripper_open = params['gripper_open']
        self.gripper_close = params['gripper_close']
        if not all(math.isfinite(value) and 0.0 <= value <= 0.8
                   for value in (self.gripper_open, self.gripper_close)):
            raise ValueError('Gripper positions must be between 0.0 and 0.8 rad.')
        duration = params['gripper_duration']
        if not math.isfinite(duration) or not 0.01 <= duration <= 60.0:
            raise ValueError('gripper_duration must be between 0.01 and 60 seconds.')
        self.gripper_duration_ns = round(duration * 1_000_000_000)
        self.gripper_received_at = None
        self.last_sim_time_ns = None
        self.gripper_pub = None
        if self.gripper_enabled:
            self.gripper_pub = self.create_publisher(
                JointTrajectory, params['gripper_controller_topic'], 10)
        self.measured = None
        self.received_at = None
        self.arm_pos = None
        self.enabled = False
        self.selected = 0
        self.arm_pub = self.create_publisher(
            JointTrajectory, params['arm_controller_topic'], 10)
        # Accept reliable and best-effort joint-state publishers; keep no backlog.
        state_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT)
        self.state_sub = self.create_subscription(
            JointState, params['joint_states_topic'], self.on_joint_state, state_qos)
        self.clock_sub = self.create_subscription(Clock, '/clock', self.on_clock, state_qos)
        self.timer = self.create_timer(
            1.0 / params['publish_rate'], self.publish_commands)
        print(HELP)
        print(f'Selected joint: {self.joint_names[self.selected]}')
        self.get_logger().info('Waiting for joint feedback; publishing is paused.')

    def on_clock(self, msg):
        """Discard old goals when Gazebo time jumps backwards."""
        stamp = msg.clock.sec * 1_000_000_000 + msg.clock.nanosec
        if self.last_sim_time_ns is not None and stamp < self.last_sim_time_ns:
            self.enabled = False
            self.homing = False
            self.arm_pos = None
            self.measured = None
            self.received_at = None
            self.gripper_received_at = None
            self.get_logger().warning(
                'Gazebo time was reset. If feedback does not resume, restart BOTH '
                'Gazebo and teleop (README steps 9 and 10). Use X in the teleop '
                'terminal to return the arm without resetting simulation time.')
        self.last_sim_time_ns = stamp

    def warn_missing_feedback(self, gripper=False):
        """Distinguish all feedback stopping from a gripper-only problem."""
        if not self.feedback_ready():
            self.get_logger().warning(
                'Joint feedback is missing or stopped. Check that Gazebo is playing. '
                'If it is playing, restart BOTH Gazebo and teleop (README steps 9 and 10). '
                'Restarting only teleop cannot restore stopped controller feedback.')
        elif gripper:
            self.get_logger().warning(
                'Arm feedback is present, but gripper feedback is missing, stale or '
                'out of range. Restart with the Robotiq scene (README steps 9 and 10).')

    def on_joint_state(self, msg):
        """Map feedback by joint name, independently of incoming array order."""
        if len(msg.name) != len(msg.position) or len(set(msg.name)) != len(msg.name):
            return
        values = dict(zip(msg.name, msg.position))
        if self.gripper_enabled and GRIPPER_COMMAND_JOINT in values:
            angle = values[GRIPPER_COMMAND_JOINT]
            valid = math.isfinite(angle) and -0.01 <= angle <= 0.81
            self.gripper_received_at = time.monotonic() if valid else None
        if not all(name in values for name in self.joint_names):
            return
        measured = [values[name] for name in self.joint_names]
        if not all(math.isfinite(value) and lo <= value <= hi
                   for value, lo, hi in zip(measured, self.lower, self.upper)):
            self.enabled = False
            self.arm_pos = None
            self.measured = None
            self.received_at = None
            return
        now = time.monotonic()
        if self.received_at is not None and now - self.received_at > self.state_timeout:
            # Do not resume an old target automatically after a paused simulator.
            self.enabled = False
            self.arm_pos = None
        self.measured = measured
        self.received_at = now

    def feedback_ready(self):
        """Reject missing, stale or out-of-range joint measurements."""
        return (
            self.measured is not None and self.received_at is not None
            and time.monotonic() - self.received_at <= self.state_timeout
            and all(lo <= value <= hi for value, lo, hi
                    in zip(self.measured, self.lower, self.upper)))

    def handle_key(self, key):
        """Handle one key; return false when the user requests exit."""
        key = key.lower()
        if key == '\x1b':
            return False
        if key in ('q', 'e'):
            self.selected = (self.selected + (-1 if key == 'q' else 1)) % 6
            print(f'Selected joint: {self.joint_names[self.selected]}')
        elif key == 'x':
            if not self.feedback_ready():
                self.warn_missing_feedback()
                return True
            self.arm_pos = self.measured[:]
            self.homing = True
            self.enabled = True
            print('Returning to startup pose. SPACE pauses; motion keys override.')
        elif key == ' ' and self.enabled:
            self.enabled = False
            self.homing = False
            self.arm_pos = None
            print('Publishing paused. Next motion starts from measured positions.')
        elif key in ('o', 'c'):
            self.command_gripper(key == 'o')
        elif key in ('w', 's', 'r', 'f', ' '):
            if not self.feedback_ready():
                self.enabled = False
                self.warn_missing_feedback()
                return True
            if not self.enabled or self.homing:
                self.arm_pos = self.measured[:]
            self.homing = False
            if key != ' ':
                indices = range(6) if key in ('r', 'f') else [self.selected]
                step = self.coarse_step if key in ('r', 'f') else self.arm_step
                delta = step if key in ('w', 'r') else -step
                for index in indices:
                    self.arm_pos[index] += delta
            self.enabled = True
        return True

    def command_gripper(self, open_gripper):
        """Command the opening axis; Gazebo synchronizes its five mimic joints."""
        if not self.gripper_enabled:
            print('Gripper disabled; use config/ur5e.yaml with the Robotiq scene.')
            return
        if (self.gripper_received_at is None
                or time.monotonic() - self.gripper_received_at > self.state_timeout):
            self.warn_missing_feedback(gripper=True)
            return
        if self.gripper_pub.get_subscription_count() == 0:
            self.get_logger().warning('Robotiq controller is not connected yet.')
            return
        angle = self.gripper_open if open_gripper else self.gripper_close
        trajectory = JointTrajectory()
        trajectory.joint_names = [GRIPPER_COMMAND_JOINT]
        point = JointTrajectoryPoint()
        point.positions = [angle]
        point.velocities = [0.0]
        point.time_from_start.sec, point.time_from_start.nanosec = divmod(
            self.gripper_duration_ns, 1_000_000_000)
        trajectory.points = [point]
        self.gripper_pub.publish(trajectory)
        print('Gripper: OPEN command sent' if open_gripper else 'Gripper: CLOSE command sent')

    def publish_commands(self):
        """Publish at 20 Hz only while enabled and feedback remains fresh."""
        if not self.enabled:
            return
        if not self.feedback_ready():
            self.enabled = False
            self.arm_pos = None
            self.get_logger().warning('Feedback lost or outside limits; publishing paused.')
            return
        if self.homing:
            # Keep the final goal: clipping the intermediate target must not
            # discard the rest of a long return motion.
            self.arm_pos = self.home[:]
            if max(abs(a - b) for a, b in zip(self.home, self.measured)) < 0.005:
                self.homing = False
                print('Startup pose reached.')
        # Prevent key repeat from accumulating a large target ahead of the robot.
        self.arm_pos = [
            min(hi, measured + self.max_offset,
                max(lo, measured - self.max_offset, target))
            for target, measured, lo, hi
            in zip(self.arm_pos, self.measured, self.lower, self.upper)
        ]
        trajectory = JointTrajectory()
        trajectory.joint_names = self.joint_names[:]
        point = JointTrajectoryPoint()
        point.positions = self.arm_pos[:]
        point.time_from_start.sec, point.time_from_start.nanosec = divmod(
            self.duration_ns, 1_000_000_000)
        trajectory.points = [point]
        self.arm_pub.publish(trajectory)


def main(args=None):
    """Process ROS callbacks and keys on one thread with reliable cleanup."""
    rclpy.init(args=args)
    node = None
    try:
        node = TeleopNode()
        with KeyboardInput() as keyboard:
            while rclpy.ok():
                rclpy.spin_once(node, timeout_sec=0.02)
                key = keyboard.get_key()
                if key and not node.handle_key(key):
                    break
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
