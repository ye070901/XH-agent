# 能源与公用设施：工业机器人 AI 巡检、预测和复检任务

- 来源 URL：[ABB shows off R&D projects in robotics, AI](https://new.abb.com/news/detail/17076/abb-shows-off-rd-projects-in-robotics-ai)；[FANUC ZDT brochure](https://www.fanucamerica.com/docs/default-source/robotics-files/fanuc-zero-down-time-brochure.pdf?keyword=fanuc+usa%3Fwtime)
- 作者/机构：ABB Robotics / FANUC America；本文由 XH-agent 基于官方资料二次整理
- 发布日期：2018 / 2025-12；本文整理日期 2026-08-28
- 来源权威等级：A
- 内容性质：官方资料的中文工程化二次整理；电力、压力和防爆场景必须由专业人员验收
- 领域标签：K4P_能源巡检AI
- 摘要：把工业机器人/巡检机构的视觉、激光和运行数据与 AI 异常检测结合，用于输送带、电机、泵、阀和站房巡检，并建立从异常告警到人工复检的闭环。

---

## 正文

### 1. 两类 AI 输入

- **设备状态 AI**：从工业机器人、伺服、泵/电机和传感器时序中识别异常趋势；
- **环境视觉 AI**：从图像、激光或热成像中定位泄漏、腐蚀、松动、异物或仪表读数异常。

工业机器人负责到达观察点、调整姿态和采样；AI 只生成异常候选和维护优先级。

### 2. 任务数据结构

```yaml
asset_id: pump_station_04
robot_pose: [x,y,z,rx,ry,rz]
sensor_bundle: [rgb, lidar, thermal, vibration]
anomaly: {type: bearing_temperature, score: 0.82}
last_service: 2026-07-12
review_status: pending
```

### 3. 复检工作流

计划任务 -> 工业机器人到位自检 -> 多传感器采集 -> AI 初筛 -> 重新观测/改变视角 -> 记录资产坐标和证据 -> 人工确认 -> 工单/停机安排 -> 回填真实故障。机器人定位不确定、通信异常或环境许可无效时回到安全点。

### 4. ZDT 数据结合

FANUC ZDT 可作为机器人资产/机群的预测分析和异常检测入口；设备时序告警与视觉巡检结果应以资产 ID 和时间窗口关联，但不能把两个异常直接合并为故障结论。维护人员仍需查看报警、日志、现场状态和厂家手册。

### 5. 安全边界

高压、高温、旋转设备、爆炸性环境和带电区域必须有隔离、许可和专用设备。AI 不能自动解除保护停机或允许人员进入危险区域。

## 适用场景

发电、输配电、泵站、输送带和公用设施中的工业机器人 AI 巡检与预测维护。

## 参考资料

1. [ABB R&D robotics and AI](https://new.abb.com/news/detail/17076/abb-shows-off-rd-projects-in-robotics-ai)。
2. [FANUC ZDT brochure](https://www.fanucamerica.com/docs/default-source/robotics-files/fanuc-zero-down-time-brochure.pdf?keyword=fanuc+usa%3Fwtime)。

<!-- self_check: K4P_20260828_018 ✓ ①②③④⑤⑥⑦ -->
