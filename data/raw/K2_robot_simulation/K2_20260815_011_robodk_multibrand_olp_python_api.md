# RoboDK 多品牌离线编程与 Python API

- **来源**：https://robodk.com/offline-programming
- **作者/机构**：RoboDK Inc.（官方文档）
- **日期**：2025-06
- **权威等级**：B
- **领域标签**：K2_OLP离线编程
- **摘要**：RoboDK 通用离线编程平台核心工作流与 Python API 脚本化。涵盖工作单元搭建（机器人/工具/工件导入与坐标对齐）、三类路径生成（目标点、曲线跟随、曲面跟随）、后处理器机制（80+ 品牌、1000+ 机器人，导出 RAPID/KRL/TP/URScript 原生代码），以及 robolink 模块的 Python 脚本化：目标点创建、MoveJ/MoveL 运动、程序生成与后处理导出。含可直接运行的 Python 码垛示例。

---

## 正文

### 一、RoboDK 定位

RoboDK 是品牌无关的离线编程平台：在统一虚拟环境中完成编程与仿真，再通过「后处理器」把中性程序翻译为各品牌控制器的原生代码。核心价值是「一次编程、多品牌导出」，适合多品牌产线或方案对比场景。

### 二、工作单元搭建

1. 新建 Station，从机器人库拖入型号（ABB / KUKA / FANUC / Yaskawa / Kawasaki 等）
2. 导入工具与工件 CAD（STEP / IGES / STL）
3. 定义坐标系：
   - 工件参考系（Reference Frame）：3 点法或坐标输入
   - 工具 TCP：在工具模型上新建 Tool，设 TCP 位置与姿态
4. 用「Calibrate Reference」使仿真坐标系与真实工装一致

### 三、路径生成方式

| 方式 | 适用场景 | 操作要点 |
|------|----------|----------|
| 目标点（Target） | 点位搬运、码垛 | 捕捉模型特征点 → 右键 Teach Target |
| 曲线跟随（Curve Follow） | 焊接、涂胶、去毛刺 | 选中边线 → Curve Follow Project → 自动生成路径点 |
| 曲面跟随（Point Follow） | 喷涂、打磨 | 选中曲面 → 设置步距 → 生成点阵 |
| 从 CAD 草图导入 | 复杂轨迹 | SolidWorks / Rhino 插件导出路径 |

### 四、后处理器机制

后处理器是存放在 `C:/RoboDK/Posts/` 的 Python 脚本，把中性程序转成目标语言：

| 品牌 | 输出语言 | 示例指令 |
|------|----------|----------|
| ABB | RAPID | `MoveL p1, v100, fine, tTool;` |
| KUKA | KRL | `LIN P1 Vel=0.1 m/s CPDAT1` |
| FANUC | TP | `L P[1] 500mm/s FINE` |
| Universal Robots | URScript | `movel(p[...], a=1.2, v=0.3)` |

导出操作：右键程序 → Select Post Processor → Generate robot program（F6）。

### 五、Python API 脚本化

`robolink` 模块提供对工作站的全对象控制。完整码垛示例（3 层 × 4 行 × 5 列）：

```python
from robolink import Robolink, ITEM_TYPE_ROBOT
from robodk import transl

RDK = Robolink()
robot = RDK.Item('ABB IRB 1200', ITEM_TYPE_ROBOT)
frame = RDK.Item('Pallet')

# 设置工具与参考系
robot.setPoseFrame(frame)
robot.setPoseTool(RDK.Item('Gripper'))

# Home 关节目标
home = RDK.AddTarget('Home', frame)
home.setAsJointTarget([0, -30, 40, 0, 90, 0])
robot.MoveJ(home)

# 码垛循环：基准点 (800, 200, 50)，行距 100、列距 120、层高 150
for layer in range(3):
    for row in range(4):
        for col in range(5):
            x = 800 + col * 120
            y = 200 + row * 100
            z = 50 + layer * 150

            app = RDK.AddTarget(f'App_{layer}_{row}_{col}', frame)
            app.setPose(transl(x, y, z + 200))      # 接近点（Z 抬高 200mm）
            tgt = RDK.AddTarget(f'T_{layer}_{row}_{col}', frame)
            tgt.setPose(transl(x, y, z))            # 放置点

            robot.MoveJ(app)
            robot.MoveL(tgt)
            robot.MoveL(app)

robot.MoveJ(home)

# 完成后：右键程序 → Generate robot program (F6) → 选择目标品牌后处理器
```

### 六、真机部署

1. 生成程序后核对后处理器输出（坐标、速度、逼近参数）
2. 通过 U 盘 / 网络导入真实控制器
3. T1 模式低速空跑 → 确认点位 → AUTO 运行

## 适用场景

- **Agent2 知识生成**：多品牌码垛/搬运程序模板与后处理导出方案
- **RAG 检索**：匹配「RoboDK 怎么导出程序」「多品牌离线编程」「robolink Python 脚本」「曲线跟随」等查询
- **学情诊断**：判断用户对「后处理器」「品牌无关编程」概念的理解

<!-- self_check: K2_20260815 ✓ ①②③④⑤⑥⑦ -->
