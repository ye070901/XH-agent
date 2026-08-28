# 运动规划与碰撞门控：工业机器人 AI 路径生成的技术约束

- 来源 URL：[NVIDIA Isaac robotics platform](https://developer.nvidia.com/isaac)；[Isaac Sim Robot Simulation](https://docs.isaacsim.omniverse.nvidia.com/latest/robot_simulation/index.html)
- 作者/机构：NVIDIA；本文由 XH-agent 基于官方资料二次整理
- 发布日期：官方页面持续更新；本文整理日期 2026-08-28
- 来源权威等级：A
- 内容性质：官方平台/文档的技术化二次整理；规划伪代码为通用表示
- 领域标签：K4P_TECH_运动规划
- 摘要：说明 AI 目标或策略如何经过工业机器人运动学、关节限位、碰撞场景、工具约束和时间预算，形成可下发轨迹。

---

## 正文

### 1. 规划问题

给定当前关节状态 `q_start`、目标末端位姿 `T_goal`、机器人模型、工具和障碍物场景，规划器寻找轨迹 `q(t)`，满足：

```text
FK(q(t_end)) ≈ T_goal
q_min <= q(t) <= q_max
|dq/dt| <= velocity_limit
|d2q/dt2| <= acceleration_limit
distance(robot, obstacle) >= safety_margin
```

AI 可以提供 `T_goal`、障碍物候选或轨迹初值，但不能绕过这些约束。

### 2. 场景版本

```yaml
robot_model: IRB1200_rev3
tool_model: vacuum_v3
collision_scene: cell_08_20260828
joint_limits_revision: safety_cfg_12
target_frame: robot_base
planning_timeout_ms: 250
```

场景中必须包含料箱、工装、输送线、相邻机器人、抓手和线缆可影响碰撞的几何体。

### 3. 规划门控

```text
request -> validate_target
        -> inverse_kinematics
        -> collision_check
        -> time_parameterize
        -> controller_limits_check
        -> send_trajectory
```

任一环节失败，都返回原因码：`NO_IK`、`JOINT_LIMIT`、`COLLISION`、`SINGULARITY`、`TIMEOUT` 或 `STALE_TARGET`。不应以“规划失败”作为自动删除障碍物的理由。

### 4. AI 与确定性规划组合

推荐让 AI 输出候选目标、抓取姿态或若干初始轨迹，确定性规划器负责最终可行性。这样可以保留可解释的失败原因，也便于在模型异常时回退到规则动作。

### 5. 验收

测试目标在工作空间边界、狭窄通道、奇异附近、动态障碍、目标移动和通信延迟下的规划成功率、耗时、最小距离、关节峰值速度和恢复时间。工业机器人安全区和急停测试必须独立执行。

## 适用场景

AI 视觉/策略与 NVIDIA Isaac、工业机器人运动规划器结合的抓取、上下料、装配和避障。

## 参考资料

1. [NVIDIA Isaac](https://developer.nvidia.com/isaac)。
2. [Isaac Sim Robot Simulation](https://docs.isaacsim.omniverse.nvidia.com/latest/robot_simulation/index.html)。

<!-- self_check: K4P_20260828_021 ✓ ①②③④⑤⑥⑦ -->
