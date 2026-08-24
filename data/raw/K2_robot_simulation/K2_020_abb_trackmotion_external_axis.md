# ABB 变位机与外部轴 TrackMotion 配置

- **来源**：https://new.abb.com/products/robotics/robotstudio
- **作者/机构**：ABB Robotics
- **日期**：2024-03-20
- **权威等级**：A
- **领域标签**：K2_焊接工艺包
- **摘要**：焊接与搬运场景常需机器人与变位机、地轨等外部轴协同运动。本文介绍 RobotStudio 中机械单元（Mechanical Unit）的配置、变位机坐标系的标定、RAPID 中 ActUnit/DeactUnit 与协调运动的编程方法，以及 MultiMove 协调作业的基本思路。

---

## 正文

外部轴（Additional Axis）指变位机、地轨、头架尾架等由控制器统一驱动的机械单元。让机器人边动、变位机边翻转，能把焊接/打磨位姿摆到最佳角度，显著提升工艺质量与可达性。

### 一、机械单元配置

1. 在 RobotStudio 中导入变位机模型，用 `Modeling → Create Mechanism` 为其建立运动链（关节、连杆、限位）。
2. `Controller → Configuration → Motion → Mechanical Units` 中把变位机定义为机械单元，类型选 `Positioner`（变位机）或 `Track`（地轨）。
3. 设置各关节的传动比、方向与零点，与真实机械一致。

### 二、变位机坐标系标定

1. 标定**变位机基坐标系**（wobj）：确定翻转轴中心与工件相对位置。
2. 标定**工件坐标系**：工件装夹后，用三点法/四点法在变位机上标出 `wobj_station`。
3. 协调运动时，工件坐标系必须挂在变位机的机械单元下，机器人才能跟随其翻转。

### 三、RAPID 协调运动编程

```rapid
MODULE PositionerDemo
    PROC WeldOnPositioner()
        ActUnit STN1;                       ! 激活变位机 STN1
        MoveJ p_home, v1000, fine, tool0;
        ! 机器人 + 变位机协调运动到焊接位
        MoveL p_weld1, v200, fine, tool_weld\WObj:=wobj_station;
        ! 焊接过程中只翻转变位机（机器人保持相对姿态）
        MoveExtJ STN1, 45, vrot10;          ! 变位机翻转 45 度
        MoveL p_weld2, v200, fine, tool_weld\WObj:=wobj_station;
        DeactUnit STN1;                     ! 释放变位机
        MoveJ p_home, v1000, fine, tool0;
    ENDPROC
ENDMODULE
```

> `MoveExtJ` 专用于外部轴单独运动；`ActUnit`/`DeactUnit` 控制是否纳入协调控制。

### 四、MultiMove 协调（多机器人/多轴）

- 需要 **MultiMove** 选项，把多个任务（Task）绑定为协调组。
- 典型应用：双机器人协同搬运大型工件，或机器人+地轨+变位机三轴协调。
- 协调组内主从关系需在 `System Parameters → Multitasking` 中定义。

### 五、常见问题

- **外部轴不动**：确认 `ActUnit` 已调用，且机械单元已正确激活。
- **协调运动路径错乱**：工件坐标系未正确绑定到变位机机械单元。
- **零点偏移**：变位机与真实设备的零点、方向未对齐，需重新标定。

## 适用场景

本文为 K2 焊接/搬运工艺包的核心补充，可用于 XH-agent 回答"变位机怎么和机器人联动""外部轴怎么编程"等问题。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
