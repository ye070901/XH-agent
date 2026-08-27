# ABB 负载识别与绝对精度指南

- 来源 URL：[ABB OmniCore Controller Software, RobotWare 8](https://library.e.abb.com/public/78694e7ead37451cb2aa714cd36bb761/3HAC098393%20AM%20Controller%20software%20OmniCore%20RW%208-en.pdf?x-sign=8Kbm3mqOA0jDyVZhLdI%2Fej0yru8gopTBu5ekXRWWsVOb%2BlpJxNnfxd2OzzoW0mw9)
- 作者/机构：ABB Robotics；本文由 XH-agent 基于官方资料二次整理
- 发布日期：RobotWare 8 Revision A，2026；本文整理日期 2026-08-27
- 来源权威等级：A
- 内容性质：基于官方资料的中文二次整理，非逐字原文
- 领域标签：K1_机器人基础理论
- 摘要：说明 ABB OmniCore Load Identification 对质量、重心、惯量识别的作用，以及负载描述、Absolute Accuracy 和 CalibWare 在定位精度管理中的关系。

---

## 正文

> 适用范围：ABB OmniCore RobotWare 8 与可用选项。精度校准和负载识别需使用适用的原厂工具与程序；本文不构成 Absolute Accuracy 或 CalibWare 的实施说明，现场应遵从对应原厂文档和授权要求。

### 1. 负载与绝对精度的关系

ABB 在 OmniCore 控制器软件手册中说明，Load Identification 可确定负载的质量、重心和惯量；Absolute Accuracy 会依据负载计算机器人挠曲，因此准确描述负载非常重要。ABB 还将 CalibWare 作为初始校准和机器人维修时用于校准 Absolute Accuracy 的工具。

这说明位置精度不是单靠机械臂出厂几何决定的。工具和工件负载造成的弹性变形、维修后的状态变化、坐标和标定数据，都可能影响机器人 TCP 在真实工位中的绝对位置。

### 2. 完整管理步骤

```text
出现精度要求提高、换工具或机器人维修后
  ↓
1. 明确任务所需的绝对精度、重复精度和测量基准
  ↓
2. 核对当前工具/工件的质量、重心、惯量与控制器负载描述
  ↓
3. 使用适用的 ABB Load Identification 确认或更新负载数据
  ↓
4. 用经批准的量测方法验证关键姿态和工艺点的 TCP 偏差
  ↓
5. 维修、搬移或偏差超限时，按原厂流程评估 CalibWare 校准需求
  ↓
6. 保存负载、校准、测量结果和软件版本，作为后续追溯基线
```

### 3. 误差诊断

若同一程序在空载和带工件时精度差异显著，应优先检查负载描述和挠曲影响；若维修后整体偏差增大，应检查标定/校准状态；若仅某工位出现偏差，还需检查用户坐标、夹具和工装定位。

### 4. 应用边界

负载识别并不能代替工位级精度验收，Absolute Accuracy 也不能消除夹具、视觉、温度和工件变形误差。高精度任务应定义统一的测量方法、验收点、环境条件和复测周期。

## 适用场景

适用于 ABB OmniCore 的精密装配、涂胶、测量、工具换型及维修后定位精度复核。

## 参考资料

1. [ABB OmniCore Controller Software, RobotWare 8](https://library.e.abb.com/public/78694e7ead37451cb2aa714cd36bb761/3HAC098393%20AM%20Controller%20software%20OmniCore%20RW%208-en.pdf?x-sign=8Kbm3mqOA0jDyVZhLdI%2Fej0yru8gopTBu5ekXRWWsVOb%2BlpJxNnfxd2OzzoW0mw9)。

<!-- self_check: K1_20260827 ✓ ①②③④⑤⑥⑦ -->
