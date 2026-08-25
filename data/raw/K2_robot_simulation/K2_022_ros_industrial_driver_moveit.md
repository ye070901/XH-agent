# ROS-Industrial 工业机器人驱动与 MoveIt 集成

- **来源**：http://wiki.ros.org/Industrial
- **作者/机构**：ROS-Industrial Consortium
- **日期**：2023-11-05
- **权威等级**：A
- **领域标签**：K2_ROS仿真
- **摘要**：ROS-Industrial 提供了工业机器人（ABB/FANUC/KUKA/UR 等）接入 ROS 的标准化驱动与协议。本文介绍 support 包、driver 包与 MoveIt 配置包的结构，`FollowJointTrajectory` 动作接口，以及 `controller.yaml`/`kinematics.yaml` 的配置要点，实现仿真与真机同源编程。

---

## 正文

ROS-Industrial（ROS-I）把工业机器人统一接入 ROS 生态，核心思想是：**同一套 MoveIt 规划代码，既可在仿真中运行，也能下发到真实控制器**，通过标准化的 `FollowJointTrajectory` 动作接口解耦上层与底层驱动。

### 一、标准三包结构

| 包类型 | 作用 | 示例 |
|--------|------|------|
| 描述包（description） | URDF/Xacro 机器人模型 | `abb_irb1200_support`、`ur_description` |
| 驱动包（driver） | 与控制器通讯、执行轨迹 | `abb_driver`、`ur_robot_driver`、`fanuc_driver` |
| 配置包（moveit_config） | MoveIt 规划配置 | `abb_irb1200_moveit_config` |

### 二、关键配置：controller.yaml

```yaml
controller_list:
  - name: ""
    action_ns: follow_joint_trajectory
    type: FollowJointTrajectory
    joints:
      - joint_1
      - joint_2
      - joint_3
      - joint_4
      - joint_5
      - joint_6
```

`type: FollowJointTrajectory` 与 `action_ns` 决定了 MoveIt 规划结果通过哪个动作服务下发。

### 三、关键配置：kinematics.yaml

```yaml
arm:
  kinematics_solver: kdl_kinematics_plugin/KDLKinematicsPlugin
  kinematics_solver_search_resolution: 0.005
  kinematics_solver_timeout: 0.05
```

默认使用 KDL 数值解；ABB、UR 等有官方 IKFast 插件（如 `ur_kinematics`），求解更快更稳。

### 四、仿真与真机切换

```bash
# 仿真：用 industrial_robot_simulator 模拟控制器
roslaunch abb_irb1200_moveit_config moveit_planning_execution.launch sim:=true

# 真机：启动 driver 连接真实控制器 IP
roslaunch abb_driver robot_interface.launch robot_ip:=192.168.1.20
```

核心在于：仿真与真机暴露**同名**的 `FollowJointTrajectory` 动作服务，上层 MoveIt 代码无需改动。

### 五、驱动通讯协议

- 工业机器人控制器不直接跑 ROS，驱动包通过**中间程序**（如 FANUC 用 KAREL 程序 `fanuc_driver`、ABB 用 RAPID 的 socket 服务）把 ROS 的关节轨迹点流式发送到控制器。
- 底层走 `simple_message` 协议，封装 `JOINT_TRAJ_PT`、`JOINT_FEEDBACK` 等消息类型。

### 六、常见问题

- **轨迹不动**：检查 `action_ns` 是否与 driver 发布的动作名一致。
- **IK 解算慢/失败**：替换为 IKFast 插件或调整 `search_resolution`。
- **真机连不上**：确认控制器 socket 端口、IP 与中间程序已启动。

## 适用场景

本文用于 XH-agent 回答"工业机器人怎么接入 ROS""仿真和真机怎么统一编程"等问题，是 K2 仿真与真实机器人桥接的关键知识。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
