# PLC 与机器人握手状态机设计

- 来源 URL：[KUKA.PLC mxAutomation](https://www.kuka.com/en-us/products/robotics-systems/software/hub-technologies/kuka%2C-d-%2Cplc-mxautomation)
- 作者/机构：KUKA；本文由 XH-agent 基于官方资料二次整理
- 发布日期：网页持续维护；本文整理日期 2026-08-27
- 来源权威等级：A
- 内容性质：基于官方资料的中文二次整理，非逐字原文
- 领域标签：K3_产线适配 / 产线集成与 PLC
- 摘要：基于 KUKA PLCopen 接口的控制职责说明，给出机器人与 PLC 的请求、确认、完成、超时和故障恢复状态机设计方法，避免以单一启动位控制复杂单元。

---

## 正文

### 1. 为什么需要状态机

KUKA 将 PLC mxAutomation 定义为把重要机器人功能接入既有 PLC 控制环境的 PLCopen 接口，同时说明安全监控、运动路径和机器人内部功能仍由机器人控制器承担。这个职责分界意味着 PLC 不能只输出一个启动位：它还必须等待机器人确认、跟踪执行状态、处理超时和安全停止，并在故障后与机器人重新建立一致状态。

### 2. 推荐信号模型

将接口拆分为 PLC 请求、机器人确认、机器人状态、任务完成、故障代码和复位许可六类。每个请求应有唯一任务号或序号，完成信号必须带回同一任务号，避免上一个周期残留的完成位被误判为当前完成。安全停止、保护门和急停应作为独立的安全状态反馈，不纳入普通生产握手的“成功完成”。

### 3. 完整调试步骤

```text
1. 定义 IDLE、READY、REQUESTED、RUNNING、DONE、FAULT、SAFE_STOP 状态及允许迁移。
2. 为每个状态建立 PLC 位、机器人反馈位、超时值和故障处理责任人。
3. 在仿真或空载环境逐一验证：单任务、重复任务、取消请求、通讯中断和故障复位。
4. 使 PLC 只在 READY 接收新任务，机器人只在请求稳定后进入 RUNNING。
5. 对超时转入 FAULT，保留任务号和诊断信息；不得自动重发运动命令。
6. 复机时先清除故障根因，再通过受控复位回到 IDLE/READY 并进行首件确认。
```

### 4. 验证原则

把状态、任务号与时间戳记录到 PLC 或上位系统，可区分机器人未收到命令、尚未执行、工艺互锁未满足或执行失败。强制写入 READY、DONE 或安全相关位会破坏状态机证据，只应在隔离测试中使用，并在恢复生产前撤销。

## 适用场景

适用于采用 PLC 统筹机器人、机床、输送线或工艺设备的单元节拍与故障恢复设计。

## 参考资料

1. [KUKA.PLC mxAutomation](https://www.kuka.com/en-us/products/robotics-systems/software/hub-technologies/kuka%2C-d-%2Cplc-mxautomation)。

<!-- self_check: K3_20260827 ✓ ①②③④⑤⑥⑦ -->
