# 机器人涂胶 Dispensing 离线编程

- **来源**：https://robodk.com/doc/en/Example-Dispensing-Liquid-dispensing-example.html
- **作者/机构**：RoboDK Inc.（官方涂胶示例，Kawasaki RS007N 机器人）
- **日期**：2024-09
- **权威等级**：B
- **领域标签**：K2_喷涂工艺包
- **摘要**：机器人涂胶/密封（Dispensing）离线编程全流程，以 RoboDK + SolidWorks 油底壳涂胶为例。覆盖 CAD 沟槽路径提取（Select Tangency + Offset Entities 偏置到槽中心）、曲线跟随（Curve Follow）项目创建与路径排序/方向调整、涂胶工具姿态（TCP 指向槽底 + rotz 旋转）、出胶量与行进速度匹配、程序生成与真机部署。含工艺参数表与路径配置要点。

---

## 正文

### 一、涂胶工艺特点

涂胶（密封/点胶）与焊接、喷涂的关键差异在于：机器人必须以**恒定速度**沿沟槽行走，同时**出胶量与速度严格匹配**，保证胶条连续、均匀、无堆积或断胶。离线编程可在虚拟环境验证路径连续性，显著减少试胶浪费。

### 二、完整 OLP 流程（RoboDK + SolidWorks）

**步骤 1 — 打开示例工作站**：`File → Open → C:/RoboDK/Examples/Plugin-SolidWorks-Liquid-Dispensing.rdk`

**步骤 2 — CAD 提取沟槽中心线**（SolidWorks）：
1. 打开油底壳 3D 模型，在平面建立草图
2. 选中沟槽一条边 → 右键 Select Tangency 选中整圈
3. 使用 Offset Entities，输入沟槽半宽（例 1.5mm）偏置到槽中心
4. 对另一侧重复，保持草图可见供 RoboDK 插件拾取

**步骤 3 — 导出路径到 RoboDK**：
1. SolidWorks 中 RoboDK 标签 → Settings → 填 Object Name（Oil Pan）与 Reference Name（Jig）
2. 点击 Auto Setup → 选中全部草图线与上表面 → OK → Done
3. 工件加载到夹具参考系，自动创建 Curve Follow 项目

**步骤 4 — 验证并排序路径**：
1. 选中 Curve Follow 项目 → Update → Simulate
2. 顺序错误时：Select curves → Reset Selection → 选首段 → Switch sense 调整方向 → Auto select next/all → Done

**步骤 5 — 工具姿态调整**：
1. Show preferred tool path 可视化工具走向
2. 设 rotz = -90° 使胶嘴垂直对准槽底
3. Update → Simulate 复查

**步骤 6 — 生成程序**：右键程序 → Generate robot program（F6），得到 `.pg` 文件

### 三、工艺参数匹配

| 参数 | 参考值 | 说明 |
|------|--------|------|
| 涂胶速度 | 40~80 mm/s | 与出胶量联动，过快断胶、过慢堆积 |
| 出胶量 | 150~400 cc/min | 视胶宽与速度 |
| 胶宽（槽宽） | 3~6 mm | 由喷嘴与速度决定 |
| 喷嘴到工件距离 | 2~5 mm | 过远胶条漂移、过近刮擦 |
| 转角减速 | 到 30~50% | 保证拐角胶量均匀 |

### 四、路径配置要点

```python
# RoboDK 曲线跟随关键参数（Python API）
from robolink import Robolink, ITEM_TYPE_ROBOT

RDK = Robolink()
robot = RDK.Item('Kawasaki RS007N', ITEM_TYPE_ROBOT)
proj = RDK.Item('Oil Pan Settings')      # Curve Follow 项目

proj.setParam('Speed', 60)               # 涂胶速度 mm/s
proj.setParam('Approach', 20)            # 接近/退离距离 mm
proj.setParam('RotZ', -90)               # 工具绕 Z 旋转（胶嘴垂直槽底）
# 在 RoboDK 界面中 Update → Simulate 复查轨迹
```

### 五、真机部署注意事项

1. 首次运行前标定工件参考系（与 SolidWorks/RoboDK 中的 Jig 一致）
2. 出胶有启停延时 → 路径首尾预留 10~20mm 提前开胶/滞后关胶
3. 转角处降低速度并加大出胶重叠，避免缺口
4. T1 模式低速空跑（不出胶）验证轨迹 → 再正式涂胶

## 适用场景

- **Agent2 知识生成**：涂胶/密封轨迹规划方案、曲线跟随配置
- **RAG 检索**：匹配「涂胶机器人怎么编程」「点胶轨迹」「曲线跟随」「出胶量匹配」「密封工艺」等查询
- **学情诊断**：判断用户对连续轨迹工艺（速度/出胶量联动）的理解

<!-- self_check: K2_20260815 ✓ ①②③④⑤⑥⑦ -->
