# FANUC SRVO-059 放大器初始化故障指南

- 来源 URL：[R-30iB Controller Maintenance Manual B-83195EN/08](https://studylib.net/doc/27459949/r-30ib-controller-maintenance-manual-b-83195en-08-4-pdf-free)
- 作者/机构：FANUC Corporation；本文由 XH-agent 基于维护手册二次整理
- 发布日期：维护手册版本 B-83195EN/08；本文整理日期 2026-08-22
- 权威等级：A（FANUC 原厂维护手册）
- 领域标签：K3_故障诊断
- 摘要：说明 FANUC SRVO-059（Servo amp init error）伺服放大器初始化失败的排查逻辑，覆盖 FSSB 光纤、CRF8/RP1 编码器回路、P5V/P3.3V 指示灯、CP5/CXA2B 电源连接及部件更换。

---

## 正文

> 本文为手册二次整理。CRF8、光纤与放大器电源检查必须断电后按控制器手册执行；不得将预期产生的临时报警误作已修复。

### 1. 故障概述

| 字段 | 内容 |
| --- | --- |
| 故障代码 | SRVO-059 |
| 故障名称 | Servo amp init error |
| 手册定义 | 伺服放大器初始化失败。 |
| 重点对象 | FSSB 光纤、CRF8/RP1 编码器回路、放大器直流电源、线追踪板和 Pulsecoder。 |

### 2. 操作步骤

```text
SRVO-059 出现
  ↓
1. 记录上电日志和伴随 SRVO-055/057/058/068
  ↓
2. 断电检查轴控卡与放大器间光纤
  ↓
3. 按手册隔离 CRF8 后受控验证 RP1/内部编码器线是否对地短路
  ↓
4. 检查放大器 P5V/P3.3V 指示及 CP5、CXA2B 连接
  ↓
5. 依次诊断放大器、线追踪板（如装有）和 Pulsecoder
  ↓
6. 低速复机并验证通讯、位置与报警历史
```

原厂动作包含检查光纤、隔离 CRF8 后判断 RP1 或内部 Pulsecoder 电缆是否对地短路、检查 P5V/P3.3V LED 与 CP5/CXA2B 连接。隔离 CRF8 时 SRVO-068 可以是预期伴随现象，不能据此把 068 当作新的根因。若需更换放大器、线追踪板或 Pulsecoder，须遵循适用机型更换与标定要求。

### 3. 复机与预防

复机前确认线缆屏蔽、接地和连接器锁紧；更换编码器后按规定检查绝对位置与 MASTERING。对柜内电源连接和光纤走线进行周期点检。

## 适用场景

适用于 FANUC R-30iB 伺服放大器上电初始化、编码器线和 FSSB 通讯综合诊断。

## 参考资料

1. [FANUC 官方手册支持入口](https://www.fanuc.co.jp/en/support/manual)。
2. [R-30iB Controller Maintenance Manual B-83195EN/08](https://studylib.net/doc/27459949/r-30ib-controller-maintenance-manual-b-83195en-08-4-pdf-free)。

<!-- self_check: K3_20260822 ✓ ①②③④⑤⑥⑦ -->
