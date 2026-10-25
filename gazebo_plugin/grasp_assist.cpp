// Exercise-only attachment: this deliberately does not simulate grasp forces.
#include <algorithm>
#include <cmath>
#include <functional>
#include <mutex>
#include <gazebo/common/Plugin.hh>
#include <gazebo/common/Events.hh>
#include <gazebo/physics/physics.hh>
#include <gazebo_ros/node.hpp>
#include <trajectory_msgs/msg/joint_trajectory.hpp>
#include <std_msgs/msg/bool.hpp>

namespace physicalai_teleop
{
class GraspAssist : public gazebo::ModelPlugin
{
public:
  void Load(gazebo::physics::ModelPtr model, sdf::ElementPtr sdf) override
  {
    model_ = model;
    node_ = gazebo_ros::Node::Get(sdf);
    status_ = node_->create_publisher<std_msgs::msg::Bool>(
      "/physicalai/grasp_held", rclcpp::QoS(1).reliable().transient_local());
    base_ = model_->GetLink("robotiq_85_base_link");
    opening_ = model_->GetJoint("robotiq_85_left_knuckle_joint");
    if (!base_ || !opening_) {
      RCLCPP_ERROR(node_->get_logger(), "Grasp assist: gripper links missing.");
      return;
    }
    subscription_ = node_->create_subscription<trajectory_msgs::msg::JointTrajectory>(
      "/robotiq_gripper_controller/joint_trajectory", 10,
      [this](trajectory_msgs::msg::JointTrajectory::ConstSharedPtr msg) {
        const auto it = std::find(msg->joint_names.begin(), msg->joint_names.end(),
          "robotiq_85_left_knuckle_joint");
        if (it == msg->joint_names.end() || msg->points.empty()) {return;}
        const auto index = std::distance(msg->joint_names.begin(), it);
        const auto & point = msg->points.back();
        if (index >= static_cast<long>(point.positions.size())) {return;}
        const double angle = point.positions[index];
        const double duration = point.time_from_start.sec +
          point.time_from_start.nanosec * 1e-9;
        if (!std::isfinite(angle) || !std::isfinite(duration) || duration < 0) {return;}
        std::lock_guard<std::mutex> lock(mutex_);
        pending_ = angle < 0.1 ? -1 : (angle >= 0.4 ? 1 : -1);
        duration_ = duration;
      });
    update_ = gazebo::event::Events::ConnectWorldUpdateEnd(
      std::bind(&GraspAssist::Update, this));
    RCLCPP_INFO(node_->get_logger(), "Exercise grasp assist enabled: C holds nearby cylinder; O releases.");
  }

  void Reset() override
  {
    Release();
    armed_ = false;
    std::lock_guard<std::mutex> lock(mutex_);
    pending_ = 0;
  }

private:
  void Release()
  {
    if (!held_) {return;}
    held_->SetGravityMode(true);
    held_->SetCollideMode("all");
    held_->SetLinearVel(ignition::math::Vector3d::Zero);
    held_->SetAngularVel(ignition::math::Vector3d::Zero);
    held_.reset();
    RCLCPP_INFO(node_->get_logger(), "Grasp assist: cylinder released.");
  }

  void Update()
  {
    const double now = model_->GetWorld()->SimTime().Double();
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (pending_ != 0) {
        armed_ = pending_ > 0 && !held_;
        deadline_ = now + duration_;
        if (pending_ < 0) {Release();}
        pending_ = 0;
      }
    }
    if (armed_ && now >= deadline_) {
      armed_ = false;
      const auto target = model_->GetWorld()->ModelByName("practice_cylinder");
      const auto link = target ? target->GetLink("cylinder") : nullptr;
      if (link) {
        const auto relative = base_->WorldPose().Inverse() * link->WorldPose();
        const auto p = relative.Pos();
        // Only the centered practice target inside the finger pads can attach.
        if (opening_->Position(0) >= 0.4 && std::abs(p.X()) < 0.012 &&
            std::abs(p.Y()) < 0.02 && p.Z() > 0.10 && p.Z() < 0.17) {
          held_ = link;
          offset_ = relative;
          held_->SetGravityMode(false);
          held_->SetCollideMode("none");
          RCLCPP_INFO(node_->get_logger(), "Grasp assist: cylinder held (simulation aid).");
        }
      }
      if (!held_) {
        RCLCPP_WARN(node_->get_logger(), "Grasp assist: center cylinder between fingers, then press O and C again.");
      }
    }
    if (held_) {
      held_->SetWorldPose(base_->WorldPose() * offset_);
      held_->SetLinearVel(ignition::math::Vector3d::Zero);
      held_->SetAngularVel(ignition::math::Vector3d::Zero);
    }
    const bool holding = static_cast<bool>(held_);
    if (now - last_status_ >= 0.1 || now < last_status_ || holding != last_holding_) {
      std_msgs::msg::Bool message;
      message.data = holding;
      status_->publish(message);
      last_status_ = now;
      last_holding_ = holding;
    }
  }

  gazebo::physics::ModelPtr model_;
  gazebo::physics::LinkPtr base_, held_;
  gazebo::physics::JointPtr opening_;
  gazebo_ros::Node::SharedPtr node_;
  rclcpp::Subscription<trajectory_msgs::msg::JointTrajectory>::SharedPtr subscription_;
  gazebo::event::ConnectionPtr update_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr status_;
  double last_status_ = -1;
  bool last_holding_ = false;
  ignition::math::Pose3d offset_;
  std::mutex mutex_;
  int pending_ = 0;
  double duration_ = 0, deadline_ = 0;
  bool armed_ = false;
};
GZ_REGISTER_MODEL_PLUGIN(GraspAssist)
}  // namespace physicalai_teleop
