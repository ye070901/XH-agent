# ABB 集成视觉标定基础指南

- 来源 URL：[ABB Integrated Vision Application Manual](https://library.e.abb.com/public/f8ed851bf78e4912814a1d5629d3fb36/3HAC067707%20AM%20Integrated%20Vision%20OmniCore-en.pdf?x-sign=7GEzWSIFhwLxUNnyQJB0d7gzrzYCfCcTi%2FH4W1sB7bUI71%2FyCF4MAduLZbirhmwL)
- 作者/机构：ABB Robotics；本文由 XH-agent 基于官方资料二次整理
- 发布日期：修订版 J，2019-2025；本文整理日期 2026-08-26
- 来源权威等级：A
- 内容性质：基于官方资料的中文二次整理，非逐字原文
- 领域标签：K2_视觉集成
- 摘要：解释 ABB Integrated Vision 中相机标定与相机到机器人标定的坐标关系，适用于视觉引导抓取前的像素到物理坐标转换与精度验证。

---

## 正文

> 适用范围：ABB Integrated Vision 与适用的 OmniCore 配置。视觉标定直接影响机器人目标位置；未验证标定结果时，禁止以生产速度执行抓取、插装或靠近人员/夹具的运动。

### 1. 两层标定关系

ABB 将相机标定定义为把图像像素坐标转换为物理空间坐标的过程，常借助棋盘格标定板完成；相机到机器人标定则建立已标定相机坐标系与机器人世界坐标系之间的关系。两者合在一起，才形成可让机器人准确到达视觉目标的共同坐标框架。

若只完成相机内部标定，机器人仍不知道相机坐标相对于机器人基座、工具和工件的位置；若只教了机器人工作对象却未完成相机标定，图像像素也不能可靠转换为毫米坐标。

### 2. 完整标定步骤

```text
为 ABB 视觉引导抓取建立坐标关系
  ↓
1. 固定相机、标定板、夹具和工作距离，记录安装状态
  ↓
2. 完成相机标定，使图像像素可转换为物理坐标
  ↓
3. 建立相机坐标与机器人工作对象用户坐标之间的关系
  ↓
4. 用已知标记点或工件位置验证转换后的 X/Y/Z 与姿态误差
  ↓
5. 在低速、无碰撞风险条件下执行单次视觉定位与接近动作
  ↓
6. 记录标定版本；相机、工装或工作距离变化后重新验证
```

### 3. 常见失效原因

标定板移动、相机支架松动、镜头焦距/曝光变化、工件高度变化或工作对象被重新示教，都可能破坏坐标关系。视觉结果偶尔正确不表示标定有效，应使用多个位置和姿态进行重复验证。

### 4. 安全与产线边界

视觉定位异常时，不应通过放大抓取速度或临时偏移来弥补。先停止自动抓取，检查图像、坐标转换、工具数据和工件到位条件。对会与夹具、传送线或人员共享空间的工位，标定变更后必须重新检查路径和安全区域。

## 适用场景

适用于 ABB OmniCore Integrated Vision 的固定相机、视觉引导抓取和视觉定位调试。

## 参考资料

1. [ABB Integrated Vision Application Manual](https://library.e.abb.com/public/f8ed851bf78e4912814a1d5629d3fb36/3HAC067707%20AM%20Integrated%20Vision%20OmniCore-en.pdf?x-sign=7GEzWSIFhwLxUNnyQJB0d7gzrzYCfCcTi%2FH4W1sB7bUI71%2FyCF4MAduLZbirhmwL)。

<!-- self_check: K2_20260826 ✓ ①②③④⑤⑥⑦ -->
