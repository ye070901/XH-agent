# 智能工厂：工业机器人 AI 单元的 OT/IT 协同与数据闭环

- 来源 URL：[Siemens Advanced robotics in tomorrow's factory](https://static.sw.cdn.siemens.com/siemens-disw-assets/public/4TCO9LYXRI6oHFk8Www3Le/en-US/Siemens-SW-Advanced-robotics-in-tomorrows-factory-White-Paper_tcm27-84778.pdf)；[NVIDIA Isaac platform](https://developer.nvidia.com/isaac)
- 作者/机构：Siemens Digital Industries Software / NVIDIA；本文由 XH-agent 基于官方资料二次整理
- 发布日期：官方白皮书/产品页；本文整理日期 2026-08-28
- 来源权威等级：A
- 内容性质：官方资料的中文工程化二次整理；架构字段为实施模板
- 领域标签：K4P_智能工厂AI
- 摘要：将工业机器人、AI 视觉/规划、PLC、MES、数字孪生和云边计算组织成可审计的智能工厂单元，重点解决数据版本、模型变更和 OT/IT 边界。

---

## 正文

### 1. 五层架构

| 层 | 作用 | 典型证据 |
|---|---|---|
| 现场感知 | 相机、力、编码器、状态 | 原始数据与时间戳 |
| AI | 识别、预测、候选规划 | 模型/策略版本、置信度 |
| 工业机器人 | 运动、工具、I/O、节拍 | 程序、控制器日志 |
| PLC/MES | 互锁、配方、追溯、排产 | 状态、工单、批次 |
| 仿真/云边 | 训练、回放、分析 | 资产、场景和发布记录 |

### 2. 单元数据契约

```yaml
cell_id: assembly_03
recipe: product_A_rev5
robot_program: rap_v18
ai_model: vision_12
camera_calibration: camcal_07
plc_project: plc_20260820
workpiece_batch: lot_842
result: {ok: true, cycle_ms: 4120, quality: pass}
```

配方切换必须原子地关联机器人程序、AI 模型、相机作业、工具/工件坐标和 PLC 参数，防止不同版本混用。

### 3. AI 变更流程

提出变更 -> 离线回放 -> 未见场景评测 -> 虚拟工业机器人验证 -> 现场低速首件 -> 质量与安全验收 -> 灰度发布 -> 监控与回退。任何模型低置信度、数据漂移或异常率上升都要有回退版本。

### 4. OT/IT 边界

云端或 IT 服务可以训练、分析和管理模型；工业机器人和安全 PLC 的实时运动/安全闭环应保持在受控 OT 网络。网络延迟、断网、证书过期或服务不可用时，单元应按确定性故障策略停机或降级。

## 适用场景

智能工厂中的工业机器人 AI 产线集成、数字孪生、换型管理和质量追溯。

## 参考资料

1. [Siemens Advanced robotics white paper](https://static.sw.cdn.siemens.com/siemens-disw-assets/public/4TCO9LYXRI6oHFk8Www3Le/en-US/Siemens-SW-Advanced-robotics-in-tomorrows-factory-White-Paper_tcm27-84778.pdf)。
2. [NVIDIA Isaac platform](https://developer.nvidia.com/isaac)。

<!-- self_check: K4P_20260828_014 ✓ ①②③④⑤⑥⑦ -->
