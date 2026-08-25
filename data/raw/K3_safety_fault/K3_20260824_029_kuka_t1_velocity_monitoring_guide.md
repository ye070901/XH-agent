# KUKA T1 速度监控配置检查指南

- 来源 URL：[KUKA Sunrise Cabinet Med 安全手册](https://www.kuka.com/-/media/kuka-downloads/manual-upload/kuka-sunrise-cabinet-med/kuka_sunrise_cabinet_med_en.pdf)
- 作者/机构：KUKA；本文由 XH-agent 基于原厂手册二次整理
- 发布日期：2021-11-26；本文整理日期 2026-08-24
- 权威等级：A（KUKA 原厂操作手册）
- 领域标签：K3_安全规范
- 摘要：说明 KUKA Sunrise 手册中 T1 手动低速与安全额定速度监控的区别。手册指出标准配置下的 T1 250 mm/s 限制未必是安全导向监控；涉及人机近距离任务时需由系统集成方按安全配置验证。

---

## 正文

> 本文针对 KUKA Sunrise Cabinet Med 手册整理。不得将本文中的速度数值迁移到其他 KUKA 控制器、应用或安全配置。

### 1. 核心原则

该手册将 T1 用于编程、示教和程序验证，并列出程序验证/点动的最大速度为 250 mm/s。同时明确：标准安全配置中的 T1 降速不构成安全导向的降速监控；如应用需要安全导向速度监控，需要在安全配置中增加相应功能，例如 Cartesian velocity monitoring。

### 2. 检查步骤

```text
T1 示教或近人调试前
  ↓
1. 确认控制器型号、软件版本和当前安全配置
  ↓
2. 识别人员可能接近的空间、工具危险和外部轴风险
  ↓
3. 确认 T1 速度限制是否属于经验证的安全功能
  ↓
4. 若需要安全导向速度监控，由授权集成人配置并验证
  ↓
5. 在可观察区域内进行最低必要速度的点动测试
  ↓
6. 记录配置、测试结果和适用工艺边界
```

### 3. 安全边界

“速度较低”不自动等于“安全”。手动引导、工具惯性、夹具运动和外部设备可能仍造成危险。不能因为处于 T1 就取消安全距离、围栏管理、逃生路径和急停准备。任何与人员协作、手动引导或限制空间相关的配置，都应经过风险评估和功能安全验证。

### 4. 预防措施

将安全配置变更纳入版本管理；更换工具、修改速度、添加外部轴或变更防护装置后重新评估 T1 调试风险。

## 适用场景

适用于 KUKA Sunrise 的示教、人工引导、近人调试和安全速度功能验收。

## 参考资料

1. [KUKA Sunrise Cabinet Med Safety Manual](https://www.kuka.com/-/media/kuka-downloads/manual-upload/kuka-sunrise-cabinet-med/kuka_sunrise_cabinet_med_en.pdf)。

<!-- self_check: K3_20260824 ✓ ①②③④⑤⑥⑦ -->
