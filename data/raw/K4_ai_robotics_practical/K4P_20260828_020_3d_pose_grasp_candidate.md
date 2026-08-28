# 3D 位姿估计与抓取候选：AI 视觉到工业机器人动作的技术管线

- 来源 URL：[MVTec HALCON 25.05 press release](https://www.mvtec.com/fileadmin/Redaktion/mvtec.com/company/press_room/press_releases/2025/2025-04-15-halcon-2505/Press_release_MVTec_HALCON_25.05.pdf)；[NVIDIA Isaac Manipulator](https://developer.nvidia.com/blog/advancing-robot-learning-perception-and-manipulation-with-latest-nvidia-isaac-release/)
- 作者/机构：MVTec / NVIDIA；本文由 XH-agent 基于官方资料二次整理
- 发布日期：2025 / 2025-01-06；本文整理日期 2026-08-28
- 来源权威等级：A
- 内容性质：官方资料的技术化二次整理；伪代码是通用工程表示
- 领域标签：K4P_TECH_3D抓取
- 摘要：从点云/图像中的对象匹配、位姿候选生成，到工业机器人抓手姿态筛选和碰撞验证。重点说明 AI 匹配分数不等于机器人可执行性。

---

## 正文

### 1. 候选生成

MVTec 将 Deep 3D Matching 定位于 bin-picking/pick-and-place；NVIDIA Isaac Manipulator 提供感知驱动的抓取工作流。工程接口可表示为：

```yaml
object_id: housing_A_0031
pose_frame: camera_depth
pose_xyz_quat: [421.4, -73.2, 118.6, 0.02, 0.71, 0.03, 0.70]
match_score: 0.91
visible_fraction: 0.76
timestamp: 2026-08-28T10:30:01Z
```

### 2. 抓取候选过滤

```text
for candidate in matched_poses:
    if candidate.model != recipe.model: continue
    if candidate.score < vision_gate: continue
    if candidate.visible_fraction < coverage_gate: continue
    p = transform(camera, robot_base, candidate.pose)
    if not reachable(p, robot, tool): continue
    if collision(p, bin, neighbors, robot): continue
    if not valid_gripper_approach(p, gripper): continue
    if not valid_payload(p, payload_model): continue
    feasible.append(p)
```

按退避空间、接近方向、姿态稳定性和预计节拍对 `feasible` 排序。无可行候选时重拍或人工处理，不应放宽碰撞体来制造“成功”。

### 3. 旋转与对称性

对称零件可能有多个等价姿态。应在模型层定义允许的旋转集合，避免 AI 输出一个视觉上正确但夹具方向错误的姿态。姿态比较可使用四元数角距离：

```text
theta = 2 * acos(abs(dot(q_candidate, q_reference)))
```

角度阈值需由工具和工艺确定。

### 4. 抓取验证

机器人到接近点前检查目标年龄、坐标变换、关节限位和碰撞；夹取后检查真空压力、夹爪开度或力传感器；退避后用相机/重量/到位传感器确认工件存在。抓取失败要区分识别、姿态、工具、载荷和执行故障。

### 5. 评测指标

分开报告匹配精度、位姿误差、候选可行率、抓取成功率、空抓率、掉落率、重试次数、规划耗时和尾部节拍。只报告 AI 检测准确率不能证明工业机器人单元可用。

## 适用场景

HALCON/NVIDIA 3D 视觉和工业机器人料箱抓取、分拣、上下料与装配。

## 参考资料

1. [MVTec HALCON 25.05](https://www.mvtec.com/fileadmin/Redaktion/mvtec.com/company/press_room/press_releases/2025/2025-04-15-halcon-2505/Press_release_MVTec_HALCON_25.05.pdf)。
2. [NVIDIA Isaac Manipulator](https://developer.nvidia.com/blog/advancing-robot-learning-perception-and-manipulation-with-latest-nvidia-isaac-release/)。

<!-- self_check: K4P_20260828_020 ✓ ①②③④⑤⑥⑦ -->
