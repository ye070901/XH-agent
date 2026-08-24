# CoppeliaSim 机器人建模与仿真

- **来源**：https://manual.coppeliarobotics.com/en/
- **作者/机构**：Coppelia Robotics
- **日期**：2023-09-25
- **权威等级**：A
- **领域标签**：K2_离线仿真
- **摘要**：CoppeliaSim（原 V-REP）是通用机器人仿真器，支持 Lua/Python/ROS 接口、正逆运动学、动力学与传感器仿真。本文讲解场景建模、模型导入（URDF）、关节控制脚本编写，以及通过 ZMQ Remote API 用 Python 控制机械臂完成离线仿真。

---

## 正文

CoppeliaSim 是面向教育与研究的通用机器人仿真平台，其优势在于**灵活的脚本接口**（嵌入式 Lua + Python/ROS Remote API）与丰富的动力学、IK 能力，适合快速搭建原型仿真。

### 一、场景与模型搭建

1. 新建场景，从模型库导入机器人（如 UR5/UR10、ABB、KUKA）。
2. 导入 CAD/URDF：`File → Import → URDF`，或拖入 `.ttm` 模型。
3. 为可动关节设置模式：`Joint → Mode` 选择 `Torque/force`（动力学）或 `Inverse kinematics`。
4. 添加视觉/接近/力传感器用于交互仿真。

### 二、嵌入式 Lua 控制脚本

每个模型可挂载 `sysCall_actuation()` 回调，在每仿真步执行：

```lua
function sysCall_init()
    jointHandle = sim.getObject('/UR5/joint')
end

function sysCall_actuation()
    -- 设置关节目标速度（度/秒）
    sim.setJointTargetVelocity(jointHandle, 30)
end
```

### 三、Python ZMQ Remote API 控制

```python
from coppeliasim_zmqremoteapi_client import RemoteAPIClient

client = RemoteAPIClient()
sim = client.require('sim')

# 获取关节句柄
joints = [sim.getObject(f'/UR5/joint{i}') for i in range(1, 7)]

# 设置目标速度
for j in joints:
    sim.setJointTargetVelocity(j, 20)

# 读取关节角度
angles = [sim.getJointPosition(j) for j in joints]
print("当前关节角:", angles)

# 停止仿真
sim.stopSimulation()
```

### 四、逆运动学（IK）使用

1. 用 `simIK` 插件为机器人建立 IK 链与 IK 组。
2. 设置目标 Dummy（如 `/UR5/target`）位姿。
3. 脚本中调用 IK 求解，让末端跟随目标：

```lua
function sysCall_actuation()
    sim.handleIkGroup(sim.handle_all_except_explicit, ikGroup, {syncWorlds=true})
end
```

### 五、与 ROS 集成

- 用 `simROS` 插件桥接，可发布/订阅 ROS 话题。
- 或在场景中挂载 ROS 接口，让 CoppeliaSim 与 MoveIt 联合仿真。

### 六、常见问题

| 现象 | 原因 | 对策 |
|------|------|------|
| 关节不动 | 关节模式未设为目标速度/力矩 | 设置 Joint Mode |
| IK 无解 | 目标超出工作空间 | 移动目标到可达范围 |
| Python 连不上 | ZMQ 端口未开 | 确认 `simRemoteApi.start(19999)` |

## 适用场景

本文用于 XH-agent 回答"CoppeliaSim 怎么建机器人""如何用 Python 控制仿真机械臂"等问题，是 K2 通用离线仿真主题的内容。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
