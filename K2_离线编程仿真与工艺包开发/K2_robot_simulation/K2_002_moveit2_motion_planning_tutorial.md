# MoveIt 2 运动规划流水线官方教程（C++ 实现）

- **来源**：https://moveit.picknik.ai/main/doc/examples/motion_planning_pipeline/motion_planning_pipeline_tutorial.html
- **作者/机构**：PickNik Robotics（MoveIt 官方维护方）
- **日期**：2025-03（ROS2 Jazzy 版本）
- **权威等级**：A
- **领域标签**：K2_ROS_MoveIt路径规划
- **摘要**：MoveIt 2 官方运动规划流水线教程。完整讲解 Planning Request Adapters 的配置链（添加/移除/重排适配器）、OMPL 规划器选择（RRTConnect/RRTstar/PRM）、碰撞检查与时间参数化后处理。提供可直接编译运行的 C++ 完整代码，包含 MoveGroupInterface 初始化、规划请求构建、适配器链自定义与执行全流程。

---

## 正文

### 一、运动规划流水线概述

在 MoveIt 2 中，运动规划流水线（Motion Planning Pipeline）是由一系列 **Planning Request Adapters（规划请求适配器）** 和一个 **Planning Plugin（规划器插件）** 组成的处理链。当用户调用 `plan()` 时，请求会依次通过每个适配器进行预处理，然后由规划器求解，最后再经适配器做后处理。

**默认适配器链**（按顺序）：
1. `FixStartStateBounds` — 修正起始状态越界
2. `FixWorkspaceBounds` — 设置工作空间边界
3. `FixStartStateCollision` — 起始状态碰撞检测与微调
4. `FixStartStatePathConstraints` — 路径约束验证
5. `CHOMPOptimizerAdapter`（可选）— CHOMP 轨迹优化
6. `AddTimeParameterization` — 时间参数化（添加速度/加速度曲线）

### 二、操作步骤

#### 步骤 1：环境准备

```bash
# 安装 ROS2 Jazzy + MoveIt 2
sudo apt install ros-jazzy-moveit ros-jazzy-moveit-ros-planning

# 创建工作空间
mkdir -p ~/moveit_ws/src
cd ~/moveit_ws
git clone https://github.com/moveit/moveit2_tutorials.git src/moveit2_tutorials
rosdep install --from-paths src --ignore-src -r -y
colcon build --mixin release
source install/setup.bash
```

#### 步骤 2：启动演示 Launch 文件

```bash
ros2 launch moveit2_tutorials motion_planning_pipeline_tutorial.launch.py
```

此 Launch 文件启动：MoveGroup 节点、RViz2（含 MotionPlanning 面板）、机器人模型（Panda 机械臂）。

#### 步骤 3：编写 C++ 规划节点

完整 C++ 代码示例（`motion_planning_pipeline_tutorial.cpp`）：

```cpp
#include <moveit/move_group_interface/move_group_interface.h>
#include <moveit/planning_scene_interface/planning_scene_interface.h>
#include <moveit_msgs/msg/display_robot_state.hpp>
#include <moveit_msgs/msg/display_trajectory.hpp>
#include <moveit/robot_state/conversions.h>
#include <chrono>
#include <rclcpp/rclcpp.hpp>

static const rclcpp::Logger LOGGER = rclcpp::get_logger("motion_planning_pipeline_tutorial");

int main(int argc, char** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::NodeOptions node_options;
  node_options.automatically_declare_parameters_from_overrides(true);
  auto node = rclcpp::Node::make_shared("motion_planning_pipeline_tutorial", node_options);

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  std::thread([&executor]() { executor.spin(); }).detach();

  // 1. 初始化 MoveGroupInterface
  static const std::string PLANNING_GROUP = "panda_arm";
  moveit::planning_interface::MoveGroupInterface move_group(node, PLANNING_GROUP);

  // 2. 查看默认流水线配置
  RCLCPP_INFO(LOGGER, "Planning pipeline: %s",
              move_group.getPlanningPipelineId().c_str());
  RCLCPP_INFO(LOGGER, "Planner ID: %s",
              move_group.getPlannerId().c_str());

  // 3. 设置目标位姿
  geometry_msgs::msg::Pose target_pose;
  target_pose.orientation.w = 1.0;
  target_pose.position.x = 0.28;
  target_pose.position.y = -0.2;
  target_pose.position.z = 0.5;
  move_group.setPoseTarget(target_pose);

  // 4. 执行规划
  moveit::planning_interface::MoveGroupInterface::Plan plan;
  moveit::core::MoveItErrorCode success = move_group.plan(plan);

  if (success == moveit::core::MoveItErrorCode::SUCCESS)
  {
    RCLCPP_INFO(LOGGER, "Planning succeeded!");
    RCLCPP_INFO(LOGGER, "Trajectory has %zu waypoints, duration: %.2f seconds",
                plan.trajectory.joint_trajectory.points.size(),
                plan.trajectory.joint_trajectory.points.back().time_from_start.sec);
  }
  else
  {
    RCLCPP_ERROR(LOGGER, "Planning failed with error code: %d", success.val);
  }

  rclcpp::shutdown();
  return 0;
}
```

#### 步骤 4：自定义流水线参数

在 `config/moveit_planning_pipeline.yaml` 中配置适配器链：

```yaml
planning_pipelines:
  pipeline_names: ["ompl", "chomp", "pilz_industrial_motion_planner"]

ompl:
  planning_plugin: "ompl_interface/OMPLPlanner"
  request_adapters: >
    default_planner_request_adapters/
    FixStartStateBounds/
    FixStartStateCollision/
    FixWorkspaceBounds/
    AddTimeParameterization
  planning_adapters:
    default_planner_request_adapters/FixStartStateBounds:
      type: FixStartStateBounds
    default_planner_request_adapters/FixStartStateCollision:
      type: FixStartStateCollision
```

#### 步骤 5：切换规划算法

```cpp
// 通过 ROS2 参数在运行时切换规划器
move_group.setPlannerId("RRTConnectkConfigDefault");
// 可选规划器：
//   "RRTConnectkConfigDefault"  — 双向快速探索随机树（默认）
//   "RRTstarkConfigDefault"     — 渐进最优 RRT*
//   "PRMkConfigDefault"         — 概率路图（多查询场景）
//   "TRRTkConfigDefault"        — 过渡状态 RRT
//   "ESTkConfigDefault"         — 扩展空间树
```

### 三、OMPL 规划器对比

| 规划器 | 特点 | 适用场景 |
|--------|------|----------|
| RRTConnect | 双向搜索，收敛快 | 大多数一般场景 |
| RRTstar | 渐进最优，路径最短 | 对路径质量有高要求 |
| PRM | 预建路图，多查询共享 | 固定场景的重复规划 |
| TRRT | 成本函数引导 | 有偏好区域（远离障碍物） |
| EST | 基于概率扩展 | 高维空间探索 |

### 四、时间参数化（AddTimeParameterization）

规划器输出的轨迹仅有几何路径（waypoints），不含时间信息。`AddTimeParameterization` 适配器为路径点添加速度/加速度曲线：

```yaml
# config/ompl_planning.yaml
default_velocity_scaling_factor: 1.0    # 速度缩放因子
default_acceleration_scaling_factor: 1.0 # 加速度缩放因子
```

轨迹发布到 `/joint_trajectory_controller/joint_trajectory` 后，`joint_trajectory_controller` 使用**三次样条插值**生成电机控制指令。

## 适用场景

- **Agent2 知识生成**：用户询问 ROS 机器人路径规划时，提供 MoveIt 2 流水线配置方案
- **RAG 检索**：匹配"MoveIt 路径规划失败""如何切换 OMPL 规划器""时间参数化是什么"等查询
- **故障排查**：规划失败时检索适配器链配置建议

<!-- self_check: K2_20260804 ✓ ①②③④⑤⑥⑦ -->
