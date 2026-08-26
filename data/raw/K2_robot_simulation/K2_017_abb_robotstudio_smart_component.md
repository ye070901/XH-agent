# ABB RobotStudio Smart Component 智能组件仿真

- **来源**：https://new.abb.com/products/robotics/robotstudio
- **作者/机构**：ABB Robotics
- **日期**：2024-05-15
- **权威等级**：A
- **领域标签**：K2_RobotStudio仿真
- **摘要**：Smart Component 是 RobotStudio 用于模拟工装、传感器、输送线等周边设备行为的智能组件。本文介绍 Source/Sink、LogicGate、Signal 与 Attacher/Detacher 等常用组件的接线方法，以及如何把组件信号绑定到机器人 IO，实现带逻辑的仿真验证。

---

## 正文

RobotStudio 中，普通图形只能"静态摆放"，无法响应信号。Smart Component 则像一块可编程的积木，用**信号（Signal）**在组件之间传递逻辑，从而模拟夹具开合、传感器触发、工件流动等真实行为，使仿真更接近产线真实工况。

### 一、常用 Smart Component 及作用

| 组件 | 作用 | 关键信号 |
|------|------|----------|
| `Source` | 生成工件副本 | `Execute`（输入触发）/ `Copy`（输出） |
| `Sink` | 回收/删除工件 | `Execute`（输入） |
| `Queue` | 缓存工件 | `Enqueue` / `Dequeue` |
| `Attacher` / `Detacher` | 把工件吸附到夹具 / 释放 | `Execute`、`Parent` |
| `LogicGate` | 逻辑与/或/非 | `InputA`、`InputB`、`Output` |
| `LogicSRLatch` | 置位/复位锁存 | `Set`、`Reset`、`Output` |
| `LinearMover` | 直线运动（如输送带） | `Execute`、`Position` |
| `PlaneSensor` | 检测物体进入区域 | `Active`、`SensorOut` |

### 二、典型搭建流程（以夹具抓放为例）

1. `Modeling → Smart Component → Empty Smart Component` 新建一个组件，命名为 `GripperSC`。
2. 在组件内添加 `Attacher`、`Detacher`、`LogicGate` 与输入/输出 `Signal`。
3. 双击组件打开「设计与信号」面板，用鼠标把输出信号拖到目标组件的输入信号上完成接线。
4. 设置 `Attacher.Parent` 为机器人夹具法兰处的坐标系，`Flange` 为机器人法兰。

```rapid
! RAPID 侧与 Smart Component 交互：通过数字信号驱动夹具逻辑
MODULE GripperLogic
    CONST robtarget pick_pos := [[500,0,800],[1,0,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];
    PROC GripperCycle()
        MoveL pick_pos, v500, fine, tool_gripper;
        SetDO do_grip, 1;          ! 触发 Smart Component 的 Attacher
        WaitTime 0.5;
        MoveL RelTool(pick_pos, 0, 0, 100), v500, fine, tool_gripper;
        SetDO do_grip, 0;          ! 触发 Detacher 释放
    ENDPROC
ENDMODULE
```

### 三、信号绑定到机器人 IO

1. 在 `Controller → Configuration → I/O System` 中确认控制器有对应的数字信号（如 `do_grip`、`di_sensor`）。
2. 在 Smart Component 的输入/输出信号上右键「Connect to IO」，把组件信号映射到控制器 IO 信号。
3. 仿真运行时，RAPID 的 `SetDO` 会驱动组件动作，组件的 `SensorOut` 会写入 `di_*`，从而形成完整闭环。

### 四、常见问题

- **工件不吸附**：检查 `Attacher.Parent` 与 `Flange` 是否设置正确，以及触发信号极性是否匹配。
- **输送带不移动**：`LinearMover` 需设置移动方向矢量与速度，并用 `Source` 持续产料。
- **信号不响应**：确认组件层级（父子）关系，信号需在同一组件树内正确拖线。

## 适用场景

本文适用于 XH-agent 检索回答中"如何在 RobotStudio 里模拟夹具/输送带/传感器逻辑"类问题，以及学情诊断中判断用户是否掌握"仿真逻辑建模"能力。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
