# ABB Integrated Vision + AI：工业机器人视觉引导标定与抓取实操

- 来源 URL：[ABB Integrated Vision Application Manual](https://library.e.abb.com/public/f8ed851bf78e4912814a1d5629d3fb36/3HAC067707%20AM%20Integrated%20Vision%20OmniCore-en.pdf?x-sign=7GEzWSIFhwLxUNnyQJB0d7gzrzYCfCcTi%2FH4W1sB7bUI71%2FyCF4MAduLZbirhmwL)
- 作者/机构：ABB Robotics；本文由 XH-agent 基于官方手册二次整理
- 发布日期：官方修订版 J（2019-2025）；本文整理日期 2026-08-28
- 来源权威等级：B
- 内容性质：官方手册的中文工程化二次整理；示例坐标与伪代码不是 ABB 原文
- 领域标签：K4P_AI视觉标定
- 摘要：把 AI 视觉检测结果转换为 ABB 工业机器人可执行的抓取姿态，重点讲相机标定、相机到机器人坐标变换、置信度门控、RAPID 任务接口和首件验收。适用于视觉引导抓取、定位和检测单元。

---

## 正文

> **安全边界**：标定或模型更新后，先在手动限速/单步模式验证。相机结果不能替代急停、安全门、SafeMove 或其他安全额定功能。

### 1. 工业机器人与 AI 的分工

| 模块 | 输入 | 输出 | 责任 |
|---|---|---|---|
| AI 视觉 | 图像/点云、配方 ID | `class_id`、像素/3D 位姿、`confidence` | 识别对象和候选姿态 |
| 坐标变换 | 相机坐标、标定参数 | 工件/机器人坐标姿态 | 单位、轴方向和时间戳一致 |
| ABB 控制器 | 候选姿态、工具/工件数据 | MoveJ/MoveL 轨迹 | 可达性、速度、I/O、程序执行 |
| 安全系统 | 门锁、光栅、区域、模式 | 允许运动/停机 | 独立于 AI 的安全判定 |

### 2. 标定数据模型

建议每次标定保存如下记录，不要只保存一个“已完成”状态：

```yaml
camera_id: cam_01
robot_model: ABB IRB 1200
controller: OmniCore
tool: tool_gripper_v3
workobject: wobj_pick_v2
intrinsic_revision: intr_20260828_01
hand_eye_revision: he_20260828_02
unit: mm
calibration_points: 12
max_position_error_mm: 0.82
validated_at: 2026-08-28T10:30:00+08:00
```

ABB 手册所描述的相机标定解决像素到物理空间的关系；相机到机器人标定解决相机坐标与机器人世界/工件坐标的关系。两者缺一不可。

### 3. 标定与上线步骤

1. 固定相机、镜头、光源、标定板和工装，记录安装状态；
2. 完成相机内部标定，检查重投影/测量误差；
3. 在工作空间不同位置采集多个标定姿态，建立相机到机器人工作对象的变换；
4. 用未参与求解的基准点验证 X/Y/Z 和姿态误差；
5. 将 AI 输出的目标姿态转换到 `wobj_pick`，检查单位、轴方向和时间戳；
6. 机器人低速接近基准点，确认工具尖端相对工件的偏差；
7. 连续运行前做空抓、遮挡、低置信度和通信中断测试。

### 4. AI 结果门控伪代码

```text
if result.status != OK:
    state = VISION_RETRY
elif result.recipe_id != active_recipe:
    state = CONFIG_FAULT
elif now - result.timestamp > max_age:
    state = STALE_TARGET
elif result.confidence < confidence_gate:
    state = MANUAL_CONFIRM
elif not inside_allowed_workspace(result.pose):
    state = POSE_FAULT
else:
    pose_wobj = transform(camera_frame, workobject_frame, result.pose)
    if robot_reachability(pose_wobj) and collision_check(pose_wobj):
        state = ROBOT_EXECUTE
    else:
        state = NO_VALID_MOTION
```

这里的阈值必须通过现场数据确定，不能把示例阈值当成 ABB 的安全参数。

### 5. 验收矩阵

| 用例 | 预期结果 | 必须留存 |
|---|---|---|
| 正常目标 | 工业机器人抓取并反馈到位 | 图像、姿态、程序日志 |
| 目标遮挡 | 重拍或转人工，不下发运动 | 视觉状态、重试次数 |
| 低置信度 | 状态机保持，等待确认 | 置信度、操作者 |
| 标定偏移 | 禁止自动运行 | 标定版本、误差报告 |
| 相机失联 | 安全停机/故障保持 | 通信日志、恢复记录 |

## 适用场景

ABB 工业机器人视觉抓取、装配定位、上下料和 AI 缺陷检测前的坐标与接口设计。

## 参考资料

1. [ABB Integrated Vision Application Manual](https://library.e.abb.com/public/f8ed851bf78e4912814a1d5629d3fb36/3HAC067707%20AM%20Integrated%20Vision%20OmniCore-en.pdf?x-sign=7GEzWSIFhwLxUNnyQJB0d7gzrzYCfCcTi%2FH4W1sB7bUI71%2FyCF4MAduLZbirhmwL)。

<!-- self_check: K4P_20260828_001 ✓ ①②③④⑤⑥⑦ -->
