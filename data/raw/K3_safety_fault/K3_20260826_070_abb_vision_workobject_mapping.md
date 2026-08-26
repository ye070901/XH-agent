# ABB 视觉工作对象映射指南

- 来源 URL：[ABB Integrated Vision Application Manual](https://library.e.abb.com/public/f8ed851bf78e4912814a1d5629d3fb36/3HAC067707%20AM%20Integrated%20Vision%20OmniCore-en.pdf?x-sign=7GEzWSIFhwLxUNnyQJB0d7gzrzYCfCcTi%2FH4W1sB7bUI71%2FyCF4MAduLZbirhmwL)
- 作者/机构：ABB Robotics；本文由 XH-agent 基于官方资料二次整理
- 发布日期：修订版 J，2019-2025；本文整理日期 2026-08-26
- 来源权威等级：A
- 内容性质：基于官方资料的中文二次整理，非逐字原文
- 领域标签：K2_视觉集成
- 摘要：整理 ABB Integrated Vision 中相机工作对象、用户坐标系和工件对象坐标系的关系，适用于定位结果正确但机器人抓取位置偏移的诊断。

---

## 正文

> 适用范围：ABB Integrated Vision。本文讲解坐标关系，不替代 RAPID 程序、工具数据和工作对象的原厂配置流程。修改坐标前应备份程序与配置，并在低速条件下验证。

### 1. 坐标关系

ABB 的 Integrated Vision 手册说明，相机到机器人标定完成后，工作对象的用户坐标系 `wobj.uframe` 与相机坐标系对应；用于被定位工件的对象坐标系通常为 `wobj.oframe`。机器人抓取位置 `robtarget` 应相对于相机工作对象表达，而不是混用基坐标、工具坐标或旧夹具坐标。

当视觉图像识别正确而机器人抓偏时，问题常不在相机识别本身，而在工作对象、工具 TCP、目标高度、姿态换算或程序使用的坐标参照不一致。

### 2. 完整诊断步骤

```text
视觉能定位工件，但机器人抓取位置存在偏移
  ↓
1. 停止自动抓取，记录视觉结果、实际偏移方向和程序使用的 wobj/tool
  ↓
2. 核对相机到机器人标定是否仍有效，检查相机和标定板是否被移动
  ↓
3. 核对 wobj.uframe 是否对应当前相机坐标关系
  ↓
4. 核对 wobj.oframe、工具 TCP、工件高度和目标姿态的定义
  ↓
5. 用已知点在低速下验证坐标转换，不直接修改量产偏移补偿
  ↓
6. 修复后验证多位置抓取、放置和异常工件处理，再恢复生产
```

### 3. 常见误区

不要用不断叠加偏移值掩盖标定失效，也不要把相机坐标、工件坐标和夹具坐标视为同一个坐标系。换工具、重标 TCP、移动相机支架、调整工作台高度或修改工件模型后，都可能要求重新验证映射。

### 4. 维护建议

为每套视觉工位保存相机标定日期、工作对象版本、工具数据、工件高度和验证样件结果。把“相机识别成功率”和“机器人抓取成功率”分开统计，可更快区分视觉算法问题和坐标转换问题。

## 适用场景

适用于 ABB 视觉引导抓取、分拣和工件定位中出现系统性位置偏差的故障定位。

## 参考资料

1. [ABB Integrated Vision Application Manual](https://library.e.abb.com/public/f8ed851bf78e4912814a1d5629d3fb36/3HAC067707%20AM%20Integrated%20Vision%20OmniCore-en.pdf?x-sign=7GEzWSIFhwLxUNnyQJB0d7gzrzYCfCcTi%2FH4W1sB7bUI71%2FyCF4MAduLZbirhmwL)。

<!-- self_check: K2_20260826 ✓ ①②③④⑤⑥⑦ -->
