# 机器人铣削打磨工艺离线编程

- **来源**：https://robodk.com/doc/en/Getting-Started.html
- **作者/机构**：RoboDK Inc.
- **日期**：2023-12-15
- **权威等级**：A
- **领域标签**：K2_工艺包开发
- **摘要**：机器人铣削/打磨/去毛刺是增材后处理与精密加工的重要应用。本文讲解 RoboDK 机器人加工（Robot Machining）的 CAM 到路径流程、G 代码/NC 文件导入、工具路径转机器人程序，以及姿态与进给参数设置，实现加工类工艺的离线编程。

---

## 正文

机器人加工（铣削、打磨、抛光、去毛刺）比搬运更依赖**连续的刀路轨迹**。RoboDK 的 Robot Machining 功能把 CAM 软件生成的刀路（G 代码 / APT / NC）转换为机器人程序，自动处理刀具姿态与可达性。

### 一、CAM 到机器人的流程

1. 在 CAM 软件（如 Fusion 360、Mastercam）中生成零件加工的刀路，导出为 **G 代码或 APT/NC 文件**。
2. 在 RoboDK 中创建 **Robot Machining Project**。
3. 导入刀路文件，映射到机器人 + 主轴工具 + 工件坐标系。
4. RoboDK 自动把刀路点转换为机器人目标点，生成运动程序。

### 二、Python API 创建加工路径

```python
from robodk import robolink
from robodk import robomath

RDK = robolink.Robolink()
robot = RDK.Item('KUKA KR 60')
tool = RDK.Item('Spindle')

# 创建加工工程
prog = RDK.AddMachiningProject("Milling_Project")
robot.setPoseFrame(RDK.Item('Part_Ref'))  # 设置工件坐标系

# 添加加工路径（点列表，含刀具姿态）
path_settings = RDK.AddMachiningProject("Cut_1")
for point in toolpath_points:
    robot.MoveL(point, blocking=False)
```

### 三、刀路姿态与进给参数

| 参数 | 说明 |
|------|------|
| 刀具姿态 | 保持刀具轴线与加工面法向一致，可加前倾角 |
| 进给速度 | 由 CAM 的 F 值映射到机器人 `MoveL` 速度 |
| 逼近/离开 | 每段刀路前加安全接近、后退动作 |
| 碰撞规避 | 开启碰撞检测，避免主轴与工件干涉 |

### 四、生成真机程序

RoboDK 后处理器（Post Processor）可把加工路径导出为：

- ABB：`MoveL` + 主轴 IO 的 RAPID 程序
- KUKA：`LIN` + 工艺调用的 KRL 程序
- FANUC：`L` + 数字量输出的 TP 程序

### 五、常见问题

| 现象 | 原因 | 对策 |
|------|------|------|
| 刀路点超可达 | 工件位置不当 | 移动工件或加外部轴 |
| 主轴干涉 | 刀具姿态不当 | 调整前倾角或路径 |
| 表面质量差 | 进给/姿态波动 | 平滑刀路、优化姿态 |

## 适用场景

本文用于 XH-agent 回答"机器人铣削怎么离线编程""刀路怎么转机器人程序"等问题，是 K2 工艺包开发（加工类）的补充。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
