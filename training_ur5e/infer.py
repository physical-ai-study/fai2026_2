"""Preview UR5e ACT predictions; --execute explicitly enables Gazebo commands."""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import threading
import traceback

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from feedback_monitor import FeedbackMonitor
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
import torch
from lerobot.common.policies.act.modeling_act import ACTPolicy

from common import (ARM, ARM_TOPIC, GRIPPER, GRIP_TOPIC, JOINTS, LOWER, UPPER,
                    load_config)


class InferenceNode(Node):
    def __init__(self, args, cfg):
        # Simulation time is supplied by the independently spun monitor.
        super().__init__('ur5e_act_infer')
        self.execute = args.execute
        self.feedback_soft_timeout = float(cfg.get('feedback_soft_timeout_seconds', .5))
        self.feedback_hard_timeout = float(cfg.get('feedback_hard_timeout_seconds', 3.0))
        if not 0 < self.feedback_soft_timeout < self.feedback_hard_timeout:
            raise ValueError('Require 0 < feedback soft timeout < hard timeout.')
        self.feedback_wait = None
        self.wait_pose = None
        self.wait_held = None
        self.last_inference_seconds = 0.
        self.last_seen_gap_sequence = 0
        self.monitor = None
        trace_dir = Path.home() / 'pai_training' / 'ur5e_runs'
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = trace_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f') + f'_{os.getpid()}.jsonl')
        self.trace_file = trace_path.open('x')
        self.write_trace('start', model_path=args.model_path, execute=args.execute)
        print(f'Run log: {trace_path}', flush=True)
        history_file = Path(args.model_path) / 'history_training_config.json'
        provenance = history_file if history_file.is_file() else Path(args.model_path) / 'ur5e_training_config.json'
        if not provenance.is_file():
            raise ValueError('Expected a local model created by ur5e/train.py (training config missing).')
        trained = json.loads(provenance.read_text())
        self.history_cfg = trained if trained.get('architecture') == 'history_elapsed_act_v1' else None
        self.history = deque()
        self.episode_start_ns = None
        self.latest_stamp_ns = None
        self.delta_anchor = None
        if self.history_cfg:
            torch.set_num_threads(trained.get('torch_threads', 2))
        if trained['joint_order'] != JOINTS or trained['fps'] != cfg['fps']:
            raise ValueError('Model joint order or sampling rate does not match inference.')
        self.policy = ACTPolicy.from_pretrained(args.model_path)
        if self.policy.config.chunk_size != cfg['chunk_size']:
            raise ValueError(
                f"Model chunk_size={self.policy.config.chunk_size}, but config requires "
                f"{cfg['chunk_size']}. Select a model trained with the matching chunk size; "
                'changing the inference setting does not resize trained model weights.')
        steps = cfg['n_action_steps']
        if not isinstance(steps, int) or not 1 <= steps <= self.policy.config.chunk_size:
            raise ValueError('n_action_steps must be between 1 and model chunk_size.')
        self.policy.config.n_action_steps = steps
        print(f'ACT chunk_size={self.policy.config.chunk_size}, n_action_steps={steps}', flush=True)
        expected = {'observation.state': (7,), 'observation.environment_state':
                    (trained['history_frames'] * 7 + 1,) if self.history_cfg else (7,)}
        for key, shape in expected.items():
            if tuple(self.policy.config.input_features[key].shape) != shape:
                raise ValueError(f'Unexpected UR5e input layout for {key}; expected {shape}.')
        if tuple(self.policy.config.output_features['action'].shape) != (7,):
            raise ValueError('Expected seven-dimensional action.')
        self.device = torch.device(cfg['device'])
        self.policy.to(self.device).eval()
        self.policy.reset()
        self.latest = None
        self.received = None
        self.last_clock = None
        self.blocked = False
        self.grip_mode = None
        self.held = False
        self.held_received = None
        self.close_started = None
        self.hold_arm = None
        self.open_since = None
        self.start_validated = False
        self.last_print = 0.0
        self.started_wall = time.monotonic()
        self.deadline = self.started_wall + args.seconds
        self.arm_pub = self.create_publisher(JointTrajectory, ARM_TOPIC, 10) if self.execute else None
        self.grip_pub = self.create_publisher(JointTrajectory, GRIP_TOPIC, 10) if self.execute else None
        # Only this monitor is spun by the background ROS executor. Policy,
        # publishing and logging remain on the main thread (no shared policy).
        self.monitor = FeedbackMonitor()
        self.control_period = 1 / cfg['fps']
        print('EXECUTE: Gazebo commands enabled.' if self.execute else
              'PREVIEW: predictions only; no arm or gripper commands will be sent.', flush=True)

    def write_trace(self, event, **fields):
        self.trace_file.write(json.dumps(dict(event=event, wall_seconds=time.time(), **fields)) + '\n')
        self.trace_file.flush()

    def feedback_diagnostics(self, snapshot):
        now = time.monotonic()
        return dict(feedback_age_seconds=(now - snapshot['received']
                                         if snapshot['received'] is not None else None),
                    clock_age_seconds=(now - snapshot['clock_received']
                                       if snapshot['clock_received'] is not None else None),
                    sim_clock_ns=snapshot['clock'], state_stamp_ns=snapshot['stamp'],
                    received_messages=snapshot['sequence'], invalid_messages=snapshot['invalid_count'],
                    max_receive_gap_seconds=snapshot['max_gap_seconds'],
                    receiver_failure=snapshot['failure'],
                    last_inference_seconds=self.last_inference_seconds)

    def stop_for_feedback(self, reason, snapshot):
        self.blocked = True
        self.policy.reset()
        self.write_trace('feedback_stopped', reason=reason, **self.feedback_diagnostics(snapshot))
        self.get_logger().error(reason + ' Commands stopped; recover the scene and restart inference.')

    def feedback_ready(self):
        s = self.monitor.snapshot()
        now = time.monotonic()
        if s['reset'] or s['failure']:
            self.stop_for_feedback('Simulation time reset or feedback receiver failed.', s)
            return False
        age = now - s['received'] if s['received'] is not None else now - self.started_wall
        if s['received'] is None and age < 10.:
            return False
        # The clock keeps a wall-time timeout even when Gazebo is paused.
        waited = now - self.feedback_wait if self.feedback_wait is not None else 0.
        if (age >= self.feedback_hard_timeout or waited >= self.feedback_hard_timeout or
                s['max_gap_seconds'] >= self.feedback_hard_timeout):
            self.stop_for_feedback('Joint feedback unavailable beyond the recovery window.', s)
            return False
        unhandled_gap = s['gap_sequence'] > self.last_seen_gap_sequence
        stale = (s['received'] is None or s['invalid'] or age > self.feedback_soft_timeout or
                 (unhandled_gap and self.feedback_wait is None) or
                 (s['clock'] is not None and s['stamp'] is not None and
                  s['clock'] - s['stamp'] > self.feedback_soft_timeout * 1e9))
        if stale:
            if self.feedback_wait is None:
                self.feedback_wait = now
                self.wait_pose = self.latest.copy() if self.latest is not None else None
                self.wait_held = self.held
                self.policy.reset()
                self.delta_anchor = None
                self.write_trace('feedback_wait', **self.feedback_diagnostics(s))
                self.get_logger().warning('Feedback delayed: waiting without sending new motion commands.')
            return False
        if self.feedback_wait is not None:
            if s['consecutive'] < 3:
                return False
            jump = float(np.max(np.abs(s['state'][:6] - self.wait_pose[:6]))) if self.wait_pose is not None else 0.
            held_changed = s['held'] != self.wait_held and self.close_started is None
            if jump > .2 or held_changed:
                self.stop_for_feedback('Pose or grasp changed during feedback interruption.', s)
                return False
            self.policy.reset()
            self.delta_anchor = None
            self.write_trace('feedback_resumed', pause_seconds=now - self.feedback_wait,
                             pose_change_rad=jump, **self.feedback_diagnostics(s))
            self.get_logger().info('Fresh feedback restored: discarding old actions and predicting again.')
            self.feedback_wait = None
            self.last_seen_gap_sequence = s['gap_sequence']
        self.latest = s['state'].copy()
        self.received = s['received']
        self.held, self.held_received = s['held'], s['held_received']
        self.last_clock = s['clock']
        self.history = deque(s['history'])
        self.latest_stamp_ns = s['stamp']
        if self.episode_start_ns is None:
            self.episode_start_ns = s['stamp']
        return True

    @staticmethod
    def trajectory(names, positions, seconds):
        message = JointTrajectory()
        message.joint_names = names
        point = JointTrajectoryPoint()
        point.positions = [float(x) for x in positions]
        # Arm demonstrations use position-only trajectories. Adding zero end
        # velocities here changes the controller interpolation on every update.
        if names == [GRIPPER]:
            point.velocities = [0.0]
        point.time_from_start.sec, point.time_from_start.nanosec = divmod(
            round(seconds * 1e9), 1_000_000_000)
        message.points = [point]
        return message

    def tick(self):
        if self.blocked:
            return
        if not self.feedback_ready():
            return
        if self.execute and (self.count_publishers(ARM_TOPIC) > 1 or
                             self.count_publishers(GRIP_TOPIC) > 1):
            self.blocked = True
            self.get_logger().error('Another command publisher exists. Stop teleop/other inference and restart.')
            return
        if self.execute and (not self.arm_pub.get_subscription_count() or
                             not self.grip_pub.get_subscription_count()):
            return
        now = (self.last_clock if self.last_clock is not None else self.latest_stamp_ns) / 1e9
        if self.execute:
            if self.held_received is None or time.monotonic() - self.held_received > 1.0:
                # Do not proceed with an old plugin that cannot report attachment.
                if (time.monotonic() - self.started_wall > 2 and
                        time.monotonic() - self.last_print > 2):
                    self.get_logger().warning('Waiting for grasp status. Restart Gazebo with the rebuilt grasp-assist plugin.')
                    self.last_print = time.monotonic()
                return
            if self.history_cfg and not self.start_validated:
                home = np.array([0., -1.57, 0., -1.57, 0., 0.])
                if np.max(np.abs(self.latest[:6] - home)) > .05 or abs(self.latest[6]) > .05 or self.held:
                    self.blocked = True
                    self.write_trace('start_rejected', state=self.latest.tolist(), held=self.held)
                    self.get_logger().error(
                        'Initial pose/open fingers not ready. Stop inference, use teleop O then X, '
                        'restore cylinder with Reset Model Poses, stop teleop and restart inference.')
                    return
                self.start_validated = True
            if self.close_started is not None:
                self.arm_pub.publish(self.trajectory(ARM, self.hold_arm, 1.0))
                if self.held:
                    self.close_started = None
                    self.policy.reset()
                    print('Grasp confirmed; resuming policy arm motion.', flush=True)
                elif now - self.close_started > 6.0:
                    self.blocked = True
                    self.get_logger().error('Grasp failed: arm stopped. Align cylinder, reset scene and restart inference.')
                return
            if self.grip_mode == 'closed' and not self.held:
                self.blocked = True
                self.arm_pub.publish(self.trajectory(ARM, self.latest[:6], 1.0))
                self.get_logger().error('Attachment lost while carrying; arm stopped.')
                return
        observation = torch.tensor(self.latest, device=self.device).unsqueeze(0)
        env_observation = observation.clone()
        if self.history_cfg:
            from history_data import environment
            count = self.history_cfg['history_frames']
            stamps = np.array([t for t, _ in self.history], dtype=np.int64)
            wanted = self.latest_stamp_ns - np.arange(count - 1, -1, -1) * round(1e9 / self.history_cfg['fps'])
            indices = np.clip(np.searchsorted(stamps, wanted, side='right') - 1, 0, len(stamps) - 1)
            states = [self.history[int(i)][1] for i in indices]
            elapsed = (self.latest_stamp_ns - self.episode_start_ns) / 1e9
            env = environment(states, elapsed, self.history_cfg['time_scale_seconds'])
            env_observation = torch.tensor(env, device=self.device).unsqueeze(0)
        inference_started = time.monotonic()
        with torch.inference_mode():
            if (self.history_cfg and self.history_cfg.get('action_representation') in
                    ('delta_from_current', 'arm_delta_gripper_absolute')
                    and len(self.policy._action_queue) == 0):
                # Residuals in a chunk share the state at prediction time,
                # not the changing measured state of each subsequent tick.
                self.delta_anchor = self.latest.copy()
            action = self.policy.select_action({'observation.state': observation,
                'observation.environment_state': env_observation}).cpu().numpy().reshape(-1)
        self.last_inference_seconds = time.monotonic() - inference_started
        # A fresh snapshot after inference prevents publishing across a clock
        # reset or a newly detected feedback interruption during computation.
        s = self.monitor.snapshot()
        if (s['reset'] or s['failure'] or s['invalid'] or
                time.monotonic() - s['received'] > self.feedback_soft_timeout or
                self.last_inference_seconds > self.feedback_soft_timeout):
            self.policy.reset()
            self.write_trace('prediction_discarded', **self.feedback_diagnostics(s))
            self.feedback_ready()
            return
        if self.history_cfg and self.history_cfg.get('action_representation') == 'delta_from_current':
            action = action + self.delta_anchor
        elif self.history_cfg and self.history_cfg.get('action_representation') == 'arm_delta_gripper_absolute':
            action = action.copy()
            action[:6] += self.delta_anchor[:6]
        if action.shape != (7,) or not np.isfinite(action).all():
            self.blocked = True
            self.get_logger().error('Invalid policy output; commands stopped.')
            return
        # Match the teleop's limits and target offset. No collision planner is used.
        arm = np.clip(action[:6], np.maximum(LOWER[:6], self.latest[:6] - .2),
                      np.minimum(UPPER[:6], self.latest[:6] + .2))
        angle = float(np.clip(action[6], 0, .455))
        # Hysteresis prevents noisy predictions toggling the gripper. Publishing
        # close on every tick would continually postpone the grasp-assist deadline.
        mode = self.grip_mode
        if mode is None:
            mode = 'closed' if angle >= .23 else 'open'
        elif mode == 'open' and angle > .28:
            mode = 'closed'
        elif mode == 'closed':
            if angle < .18:
                if self.open_since is None:
                    self.open_since = now
                if now - self.open_since >= .5:
                    mode = 'open'
            else:
                self.open_since = None
        if self.execute:
            if mode != self.grip_mode:
                self.grip_pub.publish(self.trajectory([GRIPPER],
                    [.455 if mode == 'closed' else 0.0], 4.0))
                if mode == 'closed':
                    self.close_started = now
                    self.hold_arm = self.latest[:6].copy()
                    arm = self.hold_arm
                    print('Closing: arm held stationary until grasp is confirmed.', flush=True)
                else:
                    self.open_since = None
                    print(f'Policy requested OPEN (angle={angle:.3f}); releasing cylinder.', flush=True)
            self.arm_pub.publish(self.trajectory(ARM, arm, 1.0))
        self.grip_mode = mode
        self.write_trace('prediction', sim_seconds=now,
            elapsed_seconds=(self.latest_stamp_ns - self.episode_start_ns) / 1e9 if self.history_cfg else None,
            state=self.latest.tolist(), model_target=action.tolist(), arm_target=arm.tolist(),
            gripper_mode=mode, gripper_angle=angle, held=self.held, execute=self.execute,
            **self.feedback_diagnostics(self.monitor.snapshot()))
        if time.monotonic() - self.last_print > 1:
            elapsed_text = f' elapsed={(self.latest_stamp_ns-self.episode_start_ns)/1e9:.1f}s' if self.history_cfg else ''
            print(f'arm={arm.round(3).tolist()} gripper={mode} raw_angle={angle:.3f}{elapsed_text}', flush=True)
            self.last_print = time.monotonic()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-path', required=True)
    parser.add_argument('--config')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--seconds', type=float, default=120)
    args = parser.parse_args()
    if not np.isfinite(args.seconds) or args.seconds <= 0:
        raise ValueError('--seconds must be positive and finite.')
    rclpy.init()
    node = None
    executor = None
    receiver_thread = None
    try:
        node = InferenceNode(args, load_config(args.config))
        executor = SingleThreadedExecutor()
        executor.add_node(node.monitor)

        def receive_feedback():
            try:
                executor.spin()
            except Exception:
                with node.monitor.lock:
                    node.monitor.data['failure'] = traceback.format_exc()

        receiver_thread = threading.Thread(target=receive_feedback, daemon=True)
        receiver_thread.start()
        next_tick = time.monotonic()
        while rclpy.ok() and time.monotonic() < node.deadline:
            node.tick()
            next_tick += node.control_period
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()
    except KeyboardInterrupt:
        pass
    except Exception:
        if node:
            node.write_trace('exception', traceback=traceback.format_exc())
        raise
    finally:
        if executor:
            executor.shutdown(timeout_sec=2.)
        if receiver_thread:
            receiver_thread.join(timeout=2.)
        if node:
            node.write_trace('stop', blocked=node.blocked, held=node.held,
                             deadline_reached=time.monotonic() >= node.deadline)
            node.monitor.destroy_node()
            node.destroy_node()
            node.trace_file.close()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
