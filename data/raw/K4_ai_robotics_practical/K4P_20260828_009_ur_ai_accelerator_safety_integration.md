# Universal Robots AI Accelerator：工业协作机器人 AI 视觉应用的上线检查

- 来源 URL：[AI Accelerator manual](https://www.universal-robots.com/manuals/EN/PDF/SW10_7/prod-AI-kit_online/AI%20Accelerator_en.pdf)
- 作者/机构：Universal Robots；本文由 XH-agent 基于官方手册二次整理
- 发布日期：PolyScope X 软件 10.7 文档；本文整理日期 2026-08-28
- 来源权威等级：A
- 内容性质：官方手册的中文工程化二次整理；接口字段为工程建议，需按实际组件核对
- 领域标签：K4P_AI协作机器人
- 摘要：把 AI Accelerator 的视觉/深度感知能力接入 Universal Robots 工业协作机器人时，如何管理软件版本、相机标定、目标门控、程序状态、工具风险和人机共域验收。

---

## 正文

### 1. 版本与安装基线

本文将 Universal Robots 协作机器人作为工业机器人执行层，AI Accelerator 作为视觉与 AI 感知层进行集成分析。

记录 UR 型号、控制箱、PolyScope X 版本、AI Accelerator 版本、相机驱动、网络地址、机器人程序、工具/工件坐标和安全配置备份。示例代码和数据只能作为原型起点，上线前要在目标机器人和目标工具上重新验证。

### 2. AI 到机器人接口

```yaml
target_valid: true
pose_frame: camera
pose_xyz_quat: [0.31, -0.08, 0.22, 0.0, 0.707, 0.0, 0.707]
confidence: 0.89
timestamp: 2026-08-28T10:30:01Z
error_code: 0
```

PolyScope X 程序在动作前检查目标年龄、坐标系、置信度、工作空间、工具选择、机器人模式、抓手状态和安全输入。

### 3. 上线步骤

1. 不连接工件运行 AI 和相机，确认通信与时间戳；
2. 用标定件检查相机到机器人坐标变换；
3. 低速点动到接近点，确认姿态和工具方向；
4. 固定工件进行单次抓取和放置；
5. 测试遮挡、低置信度、空抓、目标消失、相机失联、急停和恢复；
6. 通过首件和连续循环后，才扩大工件范围和速度。

### 4. 协作风险清单

工具夹点、锐边、工件坠落、意外重启、人员进入、相机误识别和 AI 规划动作变化都要纳入风险评估。协作机器人不等于任何工艺都可以人机共域；速度/力限制和保护停机应按具体应用验证。

### 5. 失败处置

结果过期或低置信度时重拍/人工确认；姿态不可达时换候选；抓手未确认时退避并故障保持；通信中断时禁止自动重试。不能用提高速度、降低安全限制或屏蔽报警解决 AI 失败。

## 适用场景

Universal Robots 工业协作机器人与 AI Accelerator 的视觉抓取、检测和柔性上下料。

## 参考资料

1. [Universal Robots AI Accelerator manual](https://www.universal-robots.com/manuals/EN/PDF/SW10_7/prod-AI-kit_online/AI%20Accelerator_en.pdf)。

<!-- self_check: K4P_20260828_009 ✓ ①②③④⑤⑥⑦ -->
