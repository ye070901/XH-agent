# FANUC SRVO-003 Deadman 开关故障指南

- 来源 URL：[R-30iB Controller Maintenance Manual B-83195EN/08](https://studylib.net/doc/27459949/r-30ib-controller-maintenance-manual-b-83195en-08-4-pdf-free)
- 作者/机构：FANUC Corporation；本文由 XH-agent 基于维护手册二次整理
- 发布日期：维护手册版本 B-83195EN/08；本文整理日期 2026-08-22
- 权威等级：A（FANUC 原厂维护手册）
- 领域标签：K3_安全规范、K3_故障诊断
- 摘要：解析 FANUC SRVO-003（DEADMAN switch released）在示教模式下的触发条件，说明三位置 Deadman 中间允许位置、示教器 Enable、模式开关及急停板的检查顺序。

---

## 正文

> 本文为手册二次整理。Deadman 是示教作业中的人员保护装置，禁止固定、捆绑或屏蔽。

### 1. 故障概述

| 字段 | 内容 |
| --- | --- |
| 故障代码 | SRVO-003 |
| 故障名称 | DEADMAN switch released |
| 手册定义 | 示教器已启用，但 Deadman 未按下；或按压过强。 |
| 关键机制 | R-30iB 使用三位置 Deadman，只有中间位置允许运动。 |

### 2. 操作步骤

```text
SRVO-003 出现
  ↓
1. 确认处于 T1/T2 示教条件，危险区内仅保留必要人员
  ↓
2. 完全松开 Deadman，再平稳按至中间允许位置
  ↓
3. 检查示教器 Enable/Disable 与操作面板模式开关位置
  ↓
4. 报警持续：检查示教器、模式开关连接和运行状态
  ↓
5. 依手册由授权人员处理示教器、模式开关或急停板
  ↓
6. 低速点动验证松开/重压均能立即停止
```

FANUC 手册要求检查 Deadman 中间位置，并确认模式开关与示教器 Enable/Disable 位置正确。若这些状态正常而报警持续，后续对象包括示教器、模式开关和急停板。操作人员不应通过持续大力握紧、胶带固定或替换非原厂安全部件来保持伺服许可。

### 3. 安全复机

验证三种状态：完全松开必须停机，中间位置才允许低速动作，强力按到底也必须停机。检查急停按钮可随时停止，并确认无远程启动信号能在示教人员未准备好时产生危险动作。

### 4. 预防措施

对高频示教岗位建立 Deadman 功能点检，检查开关手感、电缆磨损和示教器外壳裂纹；进入围栏前设定 T1/T2 并保管模式钥匙。

## 适用场景

适用于 FANUC 示教、点动和维护期间的 Deadman 安全故障处理。

## 参考资料

1. [FANUC 官方手册支持入口](https://www.fanuc.co.jp/en/support/manual)。
2. [R-30iB Controller Maintenance Manual B-83195EN/08](https://studylib.net/doc/27459949/r-30ib-controller-maintenance-manual-b-83195en-08-4-pdf-free)。

<!-- self_check: K3_20260822 ✓ ①②③④⑤⑥⑦ -->
