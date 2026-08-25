# ABB SF_EmergencyStop 复位诊断指南

- 来源 URL：[ABB AC500-S SF_EmergencyStop](https://help.plc.abb.com/AB281_en/sf_emergencystop.html?topic=sf_emergencystop)
- 作者/机构：ABB；本文由 XH-agent 基于官方资料二次整理
- 发布日期：AC500-S Safety User Manual 1.3.2；本文整理日期 2026-08-25
- 来源权威等级：A
- 内容性质：基于官方资料的中文二次整理，非逐字原文
- 领域标签：K3_故障诊断
- 摘要：说明 ABB AC500-S `SF_EmergencyStop` 功能块的复位状态、静态 Reset 报错和安全输出判断，用于排查急停已释放但安全输出仍未使能的情况。

---

## 正文

> 本文仅说明 ABB AC500-S 安全功能块的诊断逻辑。急停回路、接触器和机器人控制器的实际接线必须由具备功能安全资格的人员依据风险评估、项目安全方案和原厂手册确认。

### 1. 功能与状态含义

`SF_EmergencyStop` 用于监视急停输入。`S_EStopIn=FALSE` 表示存在安全请求，安全输出 `S_EStopOut` 必须为 FALSE；只有急停已释放、复位条件满足且无内部错误时，输出才可变为 TRUE。ABB 明确指出，复位命令不应直接启动机器，只能使重新启动成为可能。

`ResetRequest=TRUE` 表示功能块正在等待有效的复位上升沿；`Error=TRUE` 且 `DiagCode=C001` 或 `C011` 时，常见原因是 Reset 长期保持 TRUE。此时不能反复强制启动，应先让 Reset 回到 FALSE，再按状态机重新执行复位。

### 2. 完整诊断步骤

```text
安全输出 S_EStopOut = FALSE
  ↓
1. 确认急停按钮及外部急停已物理释放，检查 S_EStopIn 是否为 TRUE
  ↓
2. 读取 Ready、SafetyDemand、ResetRequest、Error 和 DiagCode
  ↓
3. 若 DiagCode 为 C001/C011：将 Reset 可靠地恢复为 FALSE
  ↓
4. 消除急停根因，确认受控设备已达到安全状态
  ↓
5. 在项目规定的复位位置给出一次短暂 Reset 上升沿
  ↓
6. 确认 Error=FALSE、S_EStopOut=TRUE；再按单元启动程序受控恢复
```

### 3. 常见误判

急停按钮已经弹起不代表安全输出必然立即为 TRUE。功能块可能仍在等待复位，或检测到静态 Reset 输入。不得为了绕过等待状态，把 `S_AutoReset` 作为通用修复手段；是否允许自动复位应由完整风险评估决定。若输入状态与现场按钮不一致，应检查双通道输入、端子、电缆及安全 I/O 诊断，而不是仅修改 PLC 程序。

### 4. 复机前检查

保存诊断码、急停触发原因和复位时间；确认围栏、光幕、工艺设备和接触器反馈均满足单元联锁条件。`S_EStopOut=TRUE` 仅代表该功能块允许安全输出，机器人是否启动仍须受模式、使能、外围联锁和启动命令共同控制。

## 适用场景

适用于采用 ABB AC500-S 安全 PLC、急停已释放但安全输出未恢复的故障定位。

## 参考资料

1. [ABB SF_EmergencyStop](https://help.plc.abb.com/AB281_en/sf_emergencystop.html?topic=sf_emergencystop)。

<!-- self_check: K3_20260825 ✓ ①②③④⑤⑥⑦ -->
