# MVTec HALCON Deep 3D Matching：工业机器人料箱抓取的候选姿态筛选

- 来源 URL：[MVTec HALCON 25.05 press release](https://www.mvtec.com/fileadmin/Redaktion/mvtec.com/company/press_room/press_releases/2025/2025-04-15-halcon-2505/Press_release_MVTec_HALCON_25.05.pdf)
- 作者/机构：MVTec Software GmbH；本文由 XH-agent 基于官方发布材料二次整理
- 发布日期：2025-04-15；本文整理日期 2026-08-28
- 来源权威等级：A
- 内容性质：官方发布材料的中文工程化二次整理；具体 HALCON 算子参数需查对应版本手册
- 领域标签：K4P_AI3D匹配
- 摘要：将 Deep 3D Matching 用于工业机器人 bin-picking 时，如何从候选姿态中筛选出可达、无碰撞、工具可用的抓取目标。内容覆盖模型、点云、姿态变换、失败重试和质量监控。

---

## 正文

### 1. 角色分工

MVTec 深度学习 3D 匹配输出零件实例和姿态候选；工业机器人根据工具、载荷和工作对象执行动作；PLC/安全控制器管理互锁和停机。匹配分数只表示视觉模型置信程度，不表示机器人轨迹可执行。

### 2. 候选数据结构

```yaml
part_model: housing_A
pose_frame: camera_depth
pose: {x_mm: 421.4, y_mm: -73.2, z_mm: 118.6, q: [0.02,0.71,0.03,0.70]}
match_score: 0.91
visible_fraction: 0.76
timestamp: 2026-08-28T10:30:01Z
```

### 3. 姿态筛选算法

```text
candidates = deep_3d_match(point_cloud, model)
for c in candidates:
    if c.model != active_recipe: reject(c, WRONG_MODEL)
    elif c.match_score < vision_gate: reject(c, LOW_SCORE)
    elif c.visible_fraction < coverage_gate: reject(c, OCCLUDED)
    else:
        p = transform(camera_frame, robot_workobject, c.pose)
        if not reachable(p, tool): reject(c, UNREACHABLE)
        elif collision(p, bin, neighbors, robot): reject(c, COLLISION)
        elif not valid_grasp_direction(p, gripper): reject(c, BAD_GRASP)
        else: accept(c, p)
```

按距离、姿态稳定性和退避空间对可行候选排序；没有可行候选时应重拍或请求人工处理，不能强行执行视觉最佳候选。

### 4. 现场数据闭环

记录每次候选被接受/拒绝的原因，以及最终抓取成功、空抓、掉落、重试和节拍。将失败点云、光照、料箱填充率和零件批次归档，分开评估模型问题、标定问题、抓手问题和机器人规划问题。

### 5. 变更影响

换零件材质、表面处理、相机角度、光源、料箱、抓手或机器人工具数据，都可能影响匹配和抓取。变更后至少重做点云质量、标定、候选筛选、碰撞和首件验收。

## 适用场景

HALCON 深度学习 3D 匹配驱动的工业机器人料箱抓取、分拣和柔性上下料。

## 参考资料

1. [MVTec HALCON 25.05 press release](https://www.mvtec.com/fileadmin/Redaktion/mvtec.com/company/press_room/press_releases/2025/2025-04-15-halcon-2505/Press_release_MVTec_HALCON_25.05.pdf)。

<!-- self_check: K4P_20260828_006 ✓ ①②③④⑤⑥⑦ -->
