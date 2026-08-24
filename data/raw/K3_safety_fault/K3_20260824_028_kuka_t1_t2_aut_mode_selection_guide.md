# KUKA T1/T2/AUT 模式切换安全指南

- 来源 URL：[KUKA Sunrise Cabinet Med 安全手册](https://www.kuka.com/-/media/kuka-downloads/manual-upload/kuka-sunrise-cabinet-med/kuka_sunrise_cabinet_med_en.pdf)
- 作者/机构：KUKA；本文由 XH-agent 基于原厂手册二次整理
- 发布日期：2021-11-26；本文整理日期 2026-08-24
- 权威等级：A（KUKA 原厂操作手册）
- 领域标签：K3_安全规范、K3_产线适配
- 摘要：整理 KUKA Sunrise 系统的 T1、T2、AUT 与 CRR 模式用途，说明模式选择应与编程、测试、自动生产和受控回撤任务匹配，防止在错误模式下操作机器人。

---

## 正文

> 本文针对 KUKA Sunrise Cabinet Med 手册整理；其他 KUKA 控制器的模式名称、速度和权限可能不同，须以对应机型手册为准。

### 1. 模式用途

| 模式 | 手册用途 | 现场原则 |
| --- | --- | --- |
| T1 | 编程、示教、程序测试 | 仅在受控手动条件下使用。 |
| T2 | 程序测试 | 不等同于自动生产许可。 |
| AUT | 自动执行程序 | 危险区无人且所有安全许可有效。 |
| CRR | 受控机器人回撤 | 用于特定安全监控触发后的受控恢复。 |

### 2. 操作步骤

```text
准备切换运行模式
  ↓
1. 明确任务：示教、调试、程序测试、自动生产或受控回撤
  ↓
2. 停止机器人并确认当前报警、门禁和安全控制状态
  ↓
3. 由授权人员通过 smartPAD 模式选择器切换到目标模式
  ↓
4. 在 T1/T2 下验证使能装置、低速条件与可视范围
  ↓
5. 切换 AUT 前清点人员并验证外围设备安全许可
  ↓
6. 先受控测试，再投入正常节拍
```

### 3. 安全边界

模式切换不能替代安全门、急停或风险评估。进入 AUT 前应确认人员离开机器人工作范围；若系统因监控空间、工具方向、力矩或位置参考问题进入 CRR，应先查明触发原因和适用恢复策略，不能把 CRR 当作规避安全监控的普通运行模式。

### 4. 预防措施

对模式选择权限、钥匙/账号、交接班状态和程序版本建立记录；在换型和维护后执行 T1 低速验证与 AUT 空载验证。

## 适用场景

适用于 KUKA Sunrise 系统的示教、测试、自动生产、故障回撤和多角色交接。

## 参考资料

1. [KUKA Sunrise Cabinet Med Safety Manual](https://www.kuka.com/-/media/kuka-downloads/manual-upload/kuka-sunrise-cabinet-med/kuka_sunrise_cabinet_med_en.pdf)。

<!-- self_check: K3_20260824 ✓ ①②③④⑤⑥⑦ -->
