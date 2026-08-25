# MoveIt2 抓取规划 Pick and Place 完整流程

- **来源**：https://moveit.picknik.ai/main/doc/examples/pick_and_place/pick_and_place_tutorial.html
- **作者/机构**：PickNik Robotics / MoveIt 社区
- **日期**：2024-02-10
- **权威等级**：A
- **领域标签**：K2_ROS仿真
- **摘要**：本文基于 MoveIt2 官方教程，讲解机械臂抓取放置（Pick and Place）的完整流程：创建规划组、设置规划场景、用 `Pick()`/`Place()` 或底层接口执行抓取、物体吸附/释放与碰撞对象管理，并给出 Python 示例，帮助在 ROS2 中搭建仿真抓取任务。

---

## 正文

MoveIt2 是 ROS2 中主流的机械臂运动规划框架。抓取放置任务的核心是：让机械臂在**避免碰撞**的前提下，移动到抓取位、闭合夹具吸附物体、再移动到放置位释放物体。整个过程依赖**规划场景（Planning Scene）**与**碰撞对象（Collision Object）**的实时维护。

### 一、环境与规划组准备

1. 通过 MoveIt Setup Assistant 为机器人生成 MoveIt 配置包，定义 `arm` 与 `gripper` 两个规划组。
2. 启动 `move_group` 节点与 RViz 可视化。
3. 用 `MoveGroupInterface` 绑定规划组进行运动规划。

```python
from moveit_configs_utils import MoveItConfigsBuilder
from moveit_configs_utils.moves import generate_parameters
from moveit import MoveItPy
from moveit.core.robot_state import RobotState

# 加载机器人 MoveIt 配置
moveit_config = (MoveItConfigsBuilder("robot", package_name="my_robot_moveit_config")
                 .robot_description("package://my_robot_description/urdf/my_robot.urdf")
                 .trajectory_execution("package://my_robot_moveit_config/config/moveit_controllers.yaml")
                 .planning_pipelines(pipelines=["ompl"])
                 .to_moveit_configs())
moveit = MoveItPy(config_dict=moveit_config)
```

### 二、设置规划场景（物体与桌子）

```python
from moveit.core.planning_scene import PlanningScene

def add_box(scene, name, size, pose):
    """在规划场景中添加一个碰撞盒"""
    with scene.mutate_world() as world:
        world.add_box(name, size, pose)

# 添加桌面与待抓取物体
add_box(planning_scene, "table", [1.0, 1.0, 0.02], [0.0, 0.0, -0.01, 1, 0, 0, 0])
add_box(planning_scene, "object", [0.05, 0.05, 0.05], [0.4, 0.0, 0.05, 1, 0, 0, 0])
```

### 三、执行抓取与放置

使用 MoveGroup 的 `pick()` / `place()` 高层接口（内部自动完成接近-抓取-抬起/落下-释放）：

```python
arm = moveit.get_planning_component("arm")

# 抓取物体
arm.pick("object", grasp_poses=[grasp_pose], pre_grasp_approach=[0.0, 0.0, 0.1],
         post_grasp_retreat=[0.0, 0.0, 0.1])

# 移动并放置
arm.set_pose_target(place_pose)
arm.plan_and_execute()
arm.place("object", place_poses=[place_pose], pre_place_approach=[0.0, 0.0, 0.1],
          post_place_retreat=[0.0, 0.0, 0.1])
```

### 四、物体吸附与释放（Attach/Detach）

抓取瞬间要把物体从"环境碰撞对象"转为"附着在夹具上"的对象，否则会与夹具自身碰撞：

```python
def attach_object(scene, obj, link):
    with scene.mutate_world() as world:
        world.move_object(obj, obj)   # 先更新位置
    with scene.mutate_attached_objects() as attached:
        attached.add_object(obj, link, gripper_grasp_pose)

def detach_object(scene, obj, link):
    with scene.mutate_attached_objects() as attached:
        attached.remove_object(obj)
```

### 五、常见问题

- **夹具与物体碰撞**：抓取前未把物体 `attach` 到夹具，需在闭合夹具后立即附着。
- **规划失败**：目标超出规划组运动范围，或起始/目标位姿存在自碰撞，调整位姿或增加中间点。
- **抓取姿态不合理**：`grasp_pose` 需保证夹具接近方向与被抓面垂直。

## 适用场景

本文为 K2「ROS/ROS2 离线仿真」主题的核心，可用于 XH-agent 回答"MoveIt2 怎么做抓取""ROS2 机械臂抓取规划"等问题。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
