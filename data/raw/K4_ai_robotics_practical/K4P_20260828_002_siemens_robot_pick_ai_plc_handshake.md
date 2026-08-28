# Siemens Robot Pick AI：工业机器人视觉取放的 PLC 握手与故障恢复

- 来源 URL：[SIMATIC Robot Pick AI and Robot Library with Universal Robots UR5](https://support.industry.siemens.com/cs/attachments/109974553/109974553_SIMATICRobotPickAI_SRL_UR_AppExample_DOC_v10_en.pdf)
- 作者/机构：Siemens AG；本文由 XH-agent 基于官方应用示例二次整理
- 发布日期：文档版本 1.0；本文整理日期 2026-08-28
- 来源权威等级：B
- 内容性质：官方应用示例的中文工程化二次整理；信号名为推荐接口，不是 Siemens 固定变量名
- 领域标签：K4P_AI视觉PLC
- 摘要：将 Siemens Robot Pick AI、SIMATIC PLC、TIA Portal、HMI 和 UR5 工业协作机器人组织成可诊断的取放单元。提供信号握手、状态机、超时和恢复逻辑，解决“AI 识别成功但机器人不应动作”的工程问题。

---

## 正文

> **安全边界**：普通 PLC/AI 信号不能充当安全输入。急停、门锁、光栅、模式和安全速度必须通过相应安全额定链路实现。

### 1. 四层接口契约

| 层 | 必填输入 | 必填输出 |
|---|---|---|
| AI 视觉 | `recipe_id`、图像时间戳 | `target_valid`、`pose`、`confidence`、`vision_code` |
| PLC | 机器人状态、抓手反馈、安全准备 | `vision_trigger`、`pick_request`、`reset_request` |
| 工业机器人 | 目标姿态、工具/工件数据 | `robot_ready`、`busy`、`complete`、`robot_fault` |
| HMI | 当前状态、故障码 | 操作者确认、复位请求 |

### 2. 建议握手时序

```text
PLC: Ready=1, VisionTrigger=1
AI : TargetValid=1, PoseValid=1, ResultSeq=n
PLC: PickRequest=1
Robot: Busy=1 -> moves to approach -> grip -> retract
Robot: GripOK=1, Complete=1
PLC: PickRequest=0, VisionTrigger=0
AI : TargetValid=0 (consume result n)
PLC: Ready=1 (next cycle)
```

`ResultSeq` 或等价的序号用于防止 PLC 重复消费同一个视觉结果。若输送带在拍照后移动，必须同时传递时间戳/位置，不能只传一个静态 XYZ。

### 3. 状态机

| 状态 | 进入条件 | 退出条件 | 超时动作 |
|---|---|---|---|
| `IDLE` | 单元已复位 | 安全准备且配方有效 | 保持 |
| `ACQUIRE` | 触发 AI 视觉 | `TargetValid=1` | 重拍或 `VISION_FAULT` |
| `VALIDATE` | 结果到达 | 置信度、坐标、序号通过 | 丢弃结果 |
| `PICK` | 机器人 Ready | `GripOK=1` | 退避并报警 |
| `PLACE` | 抓取成功 | 放置确认 | 保持安全状态 |
| `FAULT_LATCHED` | 任一严重故障 | 操作者确认且条件满足 | 禁止自动重试 |

### 4. 目标校验伪代码

```text
valid = target_valid
valid &= pose_valid
valid &= result.recipe_id == plc.active_recipe
valid &= result.seq > plc.last_consumed_seq
valid &= now - result.timestamp <= plc.max_result_age
valid &= result.confidence >= plc.ai_gate
valid &= inside_robot_workspace(result.pose)
valid &= not in_forbidden_zone(result.pose)

if valid:
    plc.last_consumed_seq = result.seq
    plc.state = PICK
else:
    plc.state = VISION_RETRY or FAULT_LATCHED
```

### 5. 故障处理

- **AI 无结果**：只重拍有限次数；超过次数保持故障，显示光照/遮挡/相机连接检查项。
- **机器人忙或不在正确模式**：不缓存过期姿态；由 PLC 重新请求新结果。
- **抓手未确认**：工业机器人退避到安全点，禁止直接重复闭合。
- **通信超时**：清除普通动作请求，保留故障并要求操作者确认。
- **HMI 复位**：复位只能清除状态机故障，不得强制置位安全输入或跳过机器人报警。

### 6. 验收测试

正常取放、错误配方、旧序号、低置信度、目标过期、空抓、抓手反馈断开、机器人急停、PLC 重启和相机重启至少各执行一次，并保存 PLC 诊断缓冲区、机器人事件日志和 AI 结果快照。

## 适用场景

Siemens PLC/TIA Portal 管理视觉 AI 和工业机器人取放、分拣、上下料的产线单元。

## 参考资料

1. [Siemens SIMATIC Robot Pick AI application example](https://support.industry.siemens.com/cs/attachments/109974553/109974553_SIMATICRobotPickAI_SRL_UR_AppExample_DOC_v10_en.pdf)。

<!-- self_check: K4P_20260828_002 ✓ ①②③④⑤⑥⑦ -->
