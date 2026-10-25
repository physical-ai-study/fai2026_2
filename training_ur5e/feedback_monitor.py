"""Receive ROS feedback independently of policy inference (no command publishers)."""
from collections import deque
import threading
import time

import numpy as np
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from sensor_msgs.msg import JointState
from rosgraph_msgs.msg import Clock
from std_msgs.msg import Bool

from common import JOINTS, ordered, valid_state


class FeedbackMonitor(Node):
    def __init__(self):
        super().__init__('ur5e_infer_feedback')
        self.lock = threading.Lock()
        self.data = dict(state=None, received=None, raw_received=None, stamp=None,
                         clock=None, clock_received=None, held=False, held_received=None,
                         reset=False, invalid=False, invalid_count=0, sequence=0,
                         max_gap_seconds=0., last_gap_seconds=0., gap_sequence=0,
                         consecutive=0, failure=None)
        self.history = deque()
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE)
        self.create_subscription(JointState, '/joint_states', self.on_state, qos)
        self.create_subscription(Clock, '/clock', self.on_clock, qos)
        self.create_subscription(Bool, '/physicalai/grasp_held', self.on_held, 1)

    def on_state(self, msg):
        now = time.monotonic()
        stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        try:
            state = ordered(msg.name, msg.position, JOINTS)
            if not valid_state(state):
                raise ValueError('Joint feedback outside limits')
        except (KeyError, ValueError):
            with self.lock:
                self.data.update(raw_received=now, invalid=True, consecutive=0)
                self.data['invalid_count'] += 1
            return
        with self.lock:
            d = self.data
            d['raw_received'] = now
            if d['stamp'] is not None and stamp < d['stamp']:
                d['reset'] = True
            # A repeated timestamp does not prove fresh simulation feedback.
            if d['stamp'] is not None and stamp == d['stamp']:
                return
            gap = now - d['received'] if d['received'] is not None else 0.
            d['max_gap_seconds'] = max(d['max_gap_seconds'], gap)
            if gap > .5:
                d['last_gap_seconds'] = gap
                d['gap_sequence'] += 1
            d['consecutive'] = d['consecutive'] + 1 if gap <= .2 and not d['invalid'] else 1
            d.update(state=np.asarray(state, dtype=np.float32), received=now,
                     stamp=stamp, invalid=False, sequence=d['sequence'] + 1)
            self.history.append((stamp, d['state']))
            while len(self.history) > 1 and stamp - self.history[0][0] > 2_000_000_000:
                self.history.popleft()

    def on_clock(self, msg):
        stamp = msg.clock.sec * 1_000_000_000 + msg.clock.nanosec
        with self.lock:
            if self.data['clock'] is not None and stamp < self.data['clock']:
                self.data['reset'] = True
            self.data.update(clock=stamp, clock_received=time.monotonic())

    def on_held(self, msg):
        with self.lock:
            self.data.update(held=bool(msg.data), held_received=time.monotonic())

    def snapshot(self):
        with self.lock:
            return dict(self.data, history=list(self.history))
