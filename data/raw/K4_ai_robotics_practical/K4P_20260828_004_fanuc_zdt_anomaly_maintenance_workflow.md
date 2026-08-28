# FANUC ZDT：工业机器人 AI 异常检测到维护工单的闭环

- 来源 URL：[FANUC America ZDT brochure](https://www.fanucamerica.com/docs/default-source/robotics-files/fanuc-zero-down-time-brochure.pdf?keyword=fanuc+usa%3Fwtime)
- 作者/机构：FANUC America；本文由 XH-agent 基于官方产品资料二次整理
- 发布日期：资料统计截至 2025-12；本文整理日期 2026-08-28
- 来源权威等级：B
- 内容性质：官方产品资料的中文工程化二次整理；告警分级和字段为推荐实施模型
- 领域标签：K4P_AI预测维护
- 摘要：把 FANUC ZDT 的预测分析、异常检测、资产/机群管理和 REST API 能力落到 FANUC 工业机器人维护流程。本文给出数据字段、异常确认、工单闭环和禁止自动化动作，避免把 AI 分数误当成故障结论。

---

## 正文

> **安全边界**：ZDT 是维护决策辅助。报警复位、伺服恢复、安全参数变更和锁定挂牌必须按 FANUC 控制器手册及现场安全规程执行。

### 1. 数据对象

```json
{
  "asset_id": "FANUC-R2-017",
  "controller": "R-30iB Plus",
  "robot_model": "M-20iD",
  "sample_time": "2026-08-28T10:30:00Z",
  "operating_mode": "AUTO",
  "cycle_count": 184223,
  "alarm_codes": [],
  "axis_features": {"A1_current": 2.1, "A2_temp": 41.8},
  "maintenance_events": [],
  "anomaly_score": 0.81,
  "model_revision": "zdt-baseline-2025-12"
}
```

生产系统还要记录工艺配方、负载、速度倍率、环境温度和最近变更，否则模型可能把换型造成的正常变化误报为机械故障。

### 2. 异常处理流程

1. 接收异常事件并校验资产、时间戳和数据完整性；
2. 与报警、运行模式、换型和维护事件对齐；
3. 检查异常是否持续、是否跨多个采样窗口；
4. 由维护人员查阅控制器报警、事件日志、线缆/机械状态和厂家手册；
5. 建立工单，安排受控停机、检查、润滑、校准或换件；
6. 回填真实原因、处理结果、停机时间和是否误报；
7. 用回填结果评估模型，而不是自动修改阈值。

### 3. 告警分级

| 级别 | 例子 | 工业机器人动作 |
|---|---|---|
| 趋势 | 温度/电流缓慢偏离 | 继续运行，安排复核 |
| 计划维护 | 异常持续且影响可靠性 | 在维护窗口检查 |
| 停机排查 | 与报警或性能骤变同时出现 | 按手册受控停机 |
| 安全相关 | 急停、门锁、保护停机 | 由安全/控制器链路处置 |

### 4. 防止错误自动化

- 不自动清除报警；
- 不自动修改速度、负载、Mastering 或安全参数；
- 不因模型“低风险”而跳过现场检查；
- 不把通信中断当作机器人健康；
- 预测结果必须能追溯到原始数据窗口和模型版本。

### 5. KPI

除“提前发现天数”外，还应统计误报率、漏报率、告警到人工确认时间、告警到工单时间、重复故障率、非计划停机小时和换件后复发率。只报告节省停机时间无法判断模型是否可靠。

## 适用场景

FANUC 工业机器人机群预测维护、异常趋势监控、备件安排和停机窗口规划。

## 参考资料

1. [FANUC America ZDT brochure](https://www.fanucamerica.com/docs/default-source/robotics-files/fanuc-zero-down-time-brochure.pdf?keyword=fanuc+usa%3Fwtime)。

<!-- self_check: K4P_20260828_004 ✓ ①②③④⑤⑥⑦ -->
