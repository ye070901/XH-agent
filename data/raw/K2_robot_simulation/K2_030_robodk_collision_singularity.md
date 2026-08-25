# RoboDK 碰撞检测与奇异点分析

- **来源**：https://robodk.com/doc/en/Collision-Avoidance.html
- **作者/机构**：RoboDK Inc.
- **日期**：2023-10-28
- **权威等级**：A
- **领域标签**：K2_故障排查
- **摘要**：RoboDK 是多品牌机器人离线编程平台，提供实时碰撞检测、碰撞规避路径规划与奇异点/关节限位分析。本文讲解碰撞检测设置、碰撞规避运动、奇异点与关节限位检查的 Python API，以及离线程序在导出前如何规避运动问题。

---

## 正文

RoboDK 以"一个平台编多品牌机器人"著称（支持 ABB/FANUC/KUKA/UR 等），其碰撞检测与奇异点分析工具能帮助工程师在**导出程序之前**发现并规避运动问题，避免真机报警。

### 一、碰撞检测设置

1. 在 RoboDK 树中为机器人、工具、工件设置正确的父子层级。
2. `Tools → Check Collisions` 开启碰撞检测，可设置：
   - 检测对象：机器人自碰撞、机器人与外部对象。
   - 自动避开：勾选后 RoboDK 会在路径规划时自动避开碰撞。
3. 运行仿真，碰撞时视图会高亮碰撞对并记录日志。

### 二、Python API 碰撞检测与规避

```python
from robodk import robolink

RDK = robolink.Robolink()
robot = RDK.Item('ABB IRB 1200')

# 开启碰撞检测
RDK.setCollisionActive(robolink.COLLISION_ON)

# 检查当前姿态是否碰撞
collisions = robot.Collisions()
if len(collisions) > 0:
    for c in collisions:
        print("碰撞对象:", c.Item1.Name(), "与", c.Item2.Name())

# 线性运动（启用碰撞规避）
robot.MoveL(target, blocking=True)
```

### 三、奇异点与关节限位分析

```python
# 检查目标是否可到达，并返回关节配置
config = robot.SolveIK(target)
if config is None:
    print("目标不可达或奇异点")
else:
    # 检查关节是否超限
    for i, j in enumerate(config.list()):
        if abs(j) > robot.JointLimits()[i][1]:
            print(f"关节 {i+1} 接近限位: {j:.1f} deg")
```

- **奇异点**：腕部轴线接近共线时，线性运动关节速度激增；RoboDK 会在规划时提示，需插入中间姿态或改用关节运动。
- **关节限位**：接近 `±360°/±180°` 限位时，需重排路径或选用不同的机器人位形（Configuration）。

### 四、导出前的运动验证清单

| 检查项 | 方法 |
|--------|------|
| 无碰撞 | `Tools → Check Collisions` 全程运行 |
| 无奇异点 | 观察关节速度曲线是否平滑 |
| 无关节超限 | 检查各轴转角在限位内 |
| 可达性 | 所有目标 SolveIK 成功 |

### 五、常见问题

| 现象 | 原因 | 对策 |
|------|------|------|
| 仿真正常真机报警 | 工具/工件坐标未对齐 | 真机重新标定 |
| MoveL 关节速度突变 | 奇异点 | 加中间点或改关节运动 |
| 碰撞规避路径怪异 | 规避目标设置过多 | 精简碰撞检测对象 |

## 适用场景

本文用于 XH-agent 回答"RoboDK 怎么做碰撞检测""奇异点怎么规避"等问题，是 K2 故障排查与离线编程质量保障的内容。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
