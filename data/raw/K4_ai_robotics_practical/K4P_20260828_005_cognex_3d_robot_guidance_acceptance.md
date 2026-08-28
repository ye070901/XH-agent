# Cognex In-Sight 3D-L4000：工业机器人 3D 引导的标定、接口与验收

- 来源 URL：[In-Sight 3D-L4000 Series Smart Camera Reference Guide](https://docs.cognex.com/is3d_2410/EN/3D-L4000_Manual.pdf)
- 作者/机构：Cognex Corporation；本文由 XH-agent 基于官方参考指南二次整理
- 发布日期：In-Sight 3D-L4000 文档 24.10；本文整理日期 2026-08-28
- 来源权威等级：B
- 内容性质：官方手册的中文工程化二次整理；字段名和验收阈值需按实际项目确认
- 领域标签：K4P_AI3D机器人引导
- 摘要：围绕 Cognex 3D-L4000 的深度学习视觉工具与工业机器人引导，给出相机作业结果、坐标变换、目标门控、机器人执行和验收记录。重点解决“检测到目标但姿态不能直接用于机器人”的常见误区。

---

## 正文

> **安全边界**：相机检测/测量结果不是安全额定输入。机器人速度、工作区、碰撞、急停和人员防护必须独立验证。

### 1. 结果接口

```json
{
  "job": "bin_pick_part_a_v4",
  "result_status": "PASS",
  "object_id": "part_a_0031",
  "pose_frame": "camera_3d",
  "pose_xyz_rpy": [412.3, -88.4, 126.7, 179.2, 0.8, 90.1],
  "quality": {"score": 0.94, "point_coverage": 0.88},
  "timestamp": "2026-08-28T10:30:01.245Z",
  "model_or_job_revision": "job_v4"
}
```

工业机器人接口还要附带 `tool_id`、`workobject_id`、抓取方向、预接近点和退避点，避免只传一个 XYZ 点。

### 2. 3D 引导流程

1. 运行与当前产品配方匹配的相机作业；
2. 检查结果状态、深度覆盖率、质量分数和时间戳；
3. 用标定变换将 `camera_3d` 姿态转换为机器人工作对象；
4. 计算接近、抓取、退避和放置姿态；
5. 检查机器人可达性、夹具干涉、料箱/工件碰撞和载荷；
6. 低速执行并等待抓手反馈；
7. 通过二次视觉或传感器确认放置结果。

### 3. 结果门控

```text
PASS
  -> recipe matches
  -> frame is known
  -> quality >= validated gate
  -> point coverage >= validated minimum
  -> target age <= conveyor latency budget
  -> robot reachability + collision check
  -> EXECUTE
否则 -> RETRY / MANUAL_CONFIRM / FAULT_LATCHED
```

阈值应按误检、漏检、空抓和节拍数据确定。不能为了提高抓取率而直接降低质量门槛。

### 4. 标定验收

使用至少三个未参与求解的空间点，分别测量 X/Y/Z 位置误差和绕工具轴的姿态误差；在料箱近端、远端、不同高度和不同光照下重复。记录相机支架、镜头、光源、工作距离、机器人工具和工件坐标版本。

### 5. 现场故障定位

| 现象 | 可能层级 | 排查顺序 |
|---|---|---|
| 所有目标同方向偏移 | 标定/坐标 | frame、单位、手眼变换 |
| 只有反光件失败 | 光学/模型 | 曝光、光源、点云覆盖、样本 |
| 目标正确但碰撞 | 机器人规划 | 抓手模型、障碍物、接近姿态 |
| 取到后掉落 | 工具/工艺 | 夹持、真空、载荷、退避 |

## 适用场景

Cognex 3D 视觉驱动的工业机器人料箱抓取、定位、测量和质量检测。

## 参考资料

1. [Cognex In-Sight 3D-L4000 Reference Guide](https://docs.cognex.com/is3d_2410/EN/3D-L4000_Manual.pdf)。

<!-- self_check: K4P_20260828_005 ✓ ①②③④⑤⑥⑦ -->
