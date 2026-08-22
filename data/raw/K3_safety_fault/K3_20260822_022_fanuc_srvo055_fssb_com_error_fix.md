# FANUC SRVO-055 FSSB 通讯故障指南

- 来源 URL：[R-30iB Controller Maintenance Manual B-83195EN/08](https://studylib.net/doc/27459949/r-30ib-controller-maintenance-manual-b-83195en-08-4-pdf-free)
- 作者/机构：FANUC Corporation；本文由 XH-agent 基于维护手册二次整理
- 发布日期：维护手册版本 B-83195EN/08；本文整理日期 2026-08-22
- 权威等级：A（FANUC 原厂维护手册）
- 领域标签：K3_故障诊断
- 摘要：说明 FANUC SRVO-055（FSSB com error 1）主板轴控卡与伺服放大器之间的光纤通讯故障，提供光纤、轴控卡和放大器的分层排查方法。

---

## 正文

> 本文为手册二次整理。光纤、轴控卡和伺服放大器更换需断电，并由授权人员防静电操作。

### 1. 故障概述

| 字段 | 内容 |
| --- | --- |
| 故障代码 | SRVO-055 |
| 故障名称 | FSSB com error 1 |
| 手册定义 | 主板上的轴控制卡与伺服放大器之间发生通讯错误。 |
| 主要影响 | 对应轴组不能建立或维持伺服通讯。 |

### 2. 操作步骤

```text
SRVO-055 出现
  ↓
1. 记录组号、轴号、上电/运行时机和伴随 FSSB 报警
  ↓
2. 断电后检查轴控卡至伺服放大器的光纤连接
  ↓
3. 检查光纤折弯、污染、松脱和端面损伤，必要时更换
  ↓
4. 光纤正常仍异常：由授权人员检查/更换轴控卡
  ↓
5. 再检查/更换伺服放大器
  ↓
6. 复机后验证报警历史和低速伺服动作
```

FANUC 手册给出的顺序为光纤电缆、轴控制卡、伺服放大器。SRVO-056 具有相同的基础通讯检查逻辑；若报警是在上电时出现或伴随 SRVO-057/058/059，应查看保险丝、直流供电、编码器回路及其他 FSSB 节点，避免只更换一个部件。

### 3. 复机与预防

断电前进行控制器备份，板卡更换后核对系统配置。保护光纤最小弯曲半径，避免与动力线挤压；柜内维护后确认所有锁扣到位。

## 适用场景

适用于 FANUC R-30iB 主板、轴控卡与伺服放大器之间的 FSSB 通讯诊断。

## 参考资料

1. [FANUC 官方手册支持入口](https://www.fanuc.co.jp/en/support/manual)。
2. [R-30iB Controller Maintenance Manual B-83195EN/08](https://studylib.net/doc/27459949/r-30ib-controller-maintenance-manual-b-83195en-08-4-pdf-free)。

<!-- self_check: K3_20260822 ✓ ①②③④⑤⑥⑦ -->
