# ABB RAPID WaitDI 数字输入等待与夹爪确认互锁

- **来源**：[ABB RAPID Instructions, Functions and Data Types](https://library.e.abb.com/public/b227fcd260204c4dbeb8a58f8002fe64/Rapid_instructions.pdf)
- **作者/机构**：ABB Robotics；本文由 XH-agent 基于技术参考手册整理
- **整理日期**：2026-09-03
- **权威等级**：A
- **领域标签**：K8_机器人I/O / RAPID
- **摘要**：明确 `WaitDI` 等待的是已配置的数字输入信号及其目标数值，给出夹爪到位确认、超时分支和仿真/真机验证边界。

---

## 正文

### 1. `WaitDI` 的对象与语义

`WaitDI` 的基本形式为 `WaitDI Signal, Value;`：程序暂停，直到指定的数字输入信号达到目标逻辑值才继续。`Signal` 是系统 I/O 配置中定义的 `signaldi` 名称，不是物理端子号，也不是任意变量名；`Value` 通常为 `0` 或 `1`。例如 `WaitDI diGripClosed, 1;` 的含义是等待已映射的夹爪“闭合到位”输入变为 1。

信号名如 `diGripClosed`、`diGripOpen` 仅为示例。真实设备可能使用常闭逻辑、真空压力开关或 PLC 汇总信号，必须先以电气图、EIO 配置和 I/O 监视页确认信号方向与来源。

### 2. 夹爪动作的最小闭环

```rapid
VAR bool gripTimeout;

PROC PickPart()
    SetDO doGripClose, 1;
    gripTimeout := FALSE;
    WaitDI diGripClosed, 1\MaxTime:=2\TimeFlag:=gripTimeout;
    IF gripTimeout THEN
        TPWrite "gripper close confirmation timeout";
        RAISE ERR_GRIPPER;
    ENDIF
ENDPROC
```

这个模式的关键不是固定“两秒”，而是让“命令已发出”和“执行器已到位”成为两个可区分状态。超时值、错误号、恢复动作和后续路径应由现场节拍、夹具风险和已批准程序定义；示例不能直接复制到真机。

### 3. 验证与故障定位

1. 先在 I/O 监视中分别触发开/闭到位信号，核对 `diGrip...` 的状态、极性和 PLC/夹具端一致。
2. 在仿真或手动低速、工作区受控时，单独执行输出和等待语句，观察输出命令、输入反馈与超时分支。
3. “一直等待”优先检查输入未接通、极性错误、信号名称/映射错误、夹具气压/真空条件或互锁前置条件。
4. “立即通过”优先检查输入常为 1、反馈接错到命令输出、仿真 Smart Component 初始状态或 PLC 强制残留。
5. 排除原因后重复验证成功路径与超时路径，并保存 I/O 表、程序版本与测试记录。

### 4. 安全边界

普通 RAPID I/O 只可实现工艺互锁，不能作为人员防护或安全停止功能。不得用 `WaitDI`、`SetDO`、超时提示或强制 I/O 替代急停、门锁、安全 PLC 或安全夹具设计。

<!-- self_check: K1_20260903 ✓ ABB-reference ✓ WaitDI ✓ gripper-feedback ✓ safety-boundary -->
