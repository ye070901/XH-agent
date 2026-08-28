# 手眼标定与坐标变换：AI 视觉结果如何进入工业机器人控制

- 来源 URL：[ABB Integrated Vision Application Manual](https://library.e.abb.com/public/f8ed851bf78e4912814a1d5629d3fb36/3HAC067707%20AM%20Integrated%20Vision%20OmniCore-en.pdf?x-sign=7GEzWSIFhwLxUNnyQJB0d7gzrzYCfCcTi%2FH4W1sB7bUI71%2FyCF4MAduLZbirhmwL)；[Cognex In-Sight 3D-L4000 Guide](https://docs.cognex.com/is3d_2410/EN/3D-L4000_Manual.pdf)
- 作者/机构：ABB Robotics / Cognex；本文由 XH-agent 基于官方手册二次整理
- 发布日期：官方修订版/24.10；本文整理日期 2026-08-28
- 来源权威等级：B
- 内容性质：官方手册的技术化二次整理；矩阵示例和误差计算为工程示例
- 领域标签：K4P_TECH_坐标变换
- 摘要：解释 AI 视觉输出从相机坐标转换到工业机器人基座/工件坐标的数学和验收方法。包括齐次变换、手眼标定、误差传播、时间戳和失效门控。

---

## 正文

### 1. 坐标链

工业机器人执行姿态 `T_base_tool`，AI 视觉通常输出 `T_camera_object`。固定相机系统可用：

```text
T_base_object = T_base_camera * T_camera_object
T_base_tool   = T_base_object * T_object_tool
```

矩阵乘法顺序不可交换；每个变换必须注明单位（mm/m）、右手/左手坐标、姿态表示（四元数/欧拉角）和时间戳。

### 2. 手眼标定数据

```yaml
camera_frame: camera_3d
robot_frame: robot_base
calibration_method: fixed_camera
poses_used: 12
validation_points: 6
translation_error_mm: 0.82
rotation_error_deg: 0.31
intrinsic_revision: cam_intr_04
extrinsic_revision: cam_robot_07
```

标定求解点和验证点要分离。用验证点计算：

```text
e_i = ||p_robot_i - p_transformed_i||_2
e_max = max(e_i)
e_rms = sqrt(sum(e_i^2) / N)
```

项目阈值必须由工艺容差和抓手间隙确定，不能把某个示例误差当作 ABB/Cognex 的通用保证。

### 3. AI 结果门控

```text
if frame_id != expected_frame: reject(FRAME_MISMATCH)
if timestamp older than conveyor_latency_budget: reject(STALE)
if confidence < validated_gate: reject(LOW_CONFIDENCE)
pose = T_base_camera * T_camera_object
if not inside_workspace(pose): reject(OUT_OF_RANGE)
if not robot_reachable(pose): reject(UNREACHABLE)
if collision_check(pose, scene) == FAIL: reject(COLLISION)
else: send_to_robot(pose)
```

### 4. 误差定位

所有目标同向偏移：查外参、工件坐标或单位；误差随姿态变化：查 TCP、旋转顺序或手眼模型；误差随时间变化：查相机支架、输送带同步或目标移动；只有反光/遮挡件失败：查 AI/点云质量，不要先改机器人点位。

### 5. 验收

在工作空间近/远端、不同高度、姿态、光照和输送速度下测量位置/姿态误差；保存原始图像、AI 结果、变换版本、机器人日志和最终落点。相机、镜头、支架、工具或工作对象改变后重新验证。

## 适用场景

AI 视觉驱动 ABB、Cognex 或其他工业机器人抓取、定位、装配和检测。

## 参考资料

1. [ABB Integrated Vision Application Manual](https://library.e.abb.com/public/f8ed851bf78e4912814a1d5629d3fb36/3HAC067707%20AM%20Integrated%20Vision%20OmniCore-en.pdf?x-sign=7GEzWSIFhwLxUNnyQJB0d7gzrzYCfCcTi%2FH4W1sB7bUI71%2FyCF4MAduLZbirhmwL)。
2. [Cognex In-Sight 3D-L4000 Guide](https://docs.cognex.com/is3d_2410/EN/3D-L4000_Manual.pdf)。

<!-- self_check: K4P_20260828_019 ✓ ①②③④⑤⑥⑦ -->
