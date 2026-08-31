# AI+工业机器人系统架构：感知-规划-控制闭环与边缘计算

- 来源 URL：[LLM-Guided Safety Agent for Edge Robotics with an ISO-Compliant Perception-Compute-Control Architecture — arXiv](https://arxiv.org/abs/2604.20193)；[Edge-intelligent vision-based robotic manipulation for real-time pick-and-place — Scientific Reports](https://link.springer.com/article/10.1038/s41598-026-62645-6)
- 作者/机构：arXiv / Scientific Reports；本文由 XH-agent 基于公开论文二次整理
- 发布日期：2026；本文整理日期 2026-08-29
- 来源权威等级：B
- 内容性质：公开论文的中文归纳；架构命名（感知-计算-控制等）为通用学术表述
- 领域标签：K4B_系统架构
- 摘要：解释「AI + 工业机器人」最常见的系统组织方式：感知 → 规划/决策 → 控制/执行的闭环，模块解耦与分层控制，边缘计算与实时安全边界，以及为什么工业落地必须把「概率性的 AI 性能」转化成「有保证的时序」。

---

## 正文

### 1. 核心闭环：感知 → 规划 → 控制

AI 驱动的工业机器人普遍组织为一条闭环：

```text
感知（perception）→ 规划/决策（planning/decision）→ 控制/执行（control/action）→ 反馈回到感知
```

- **感知层**：视觉（YOLO/CNN）、深度/点云、力觉/触觉、多模态传感器融合；
- **规划/决策层**：任务分解、运动规划、大模型/视觉-语言-动作（VLA）推理或强化学习策略；
- **控制/执行层**：实时电机控制、轨迹执行、底层闭环伺服。

这条链模仿人类「感知-思考-行动」，是几乎所有 AI 机器人架构的骨架。

### 2. 模块解耦 + 分层控制

工业落地的关键原则是**把感知/决策与底层控制解耦**，形成分层结构：

- **上层（System-1 / 规划型）**：高层的 VLA 模型、LLM、强化学习策略，负责「想做什么」；
- **下层（System-2 / 反射型）**：快速、确定性的底层控制器，根据实时传感反馈执行「怎么做」，闭环扭矩/速度/位置。

设计动机是：**大模型推理慢、有概率性，不能直接驱动毫秒级的伺服控制**；下层用确定性控制兜底，才能保证安全与实时。

### 3. 边缘智能与实时安全边界

工业场景里，延迟是硬指标。边缘智能方案把「感知、标定、运动规划、控制」合并进一个仿真式闭环以压低延迟。

一个代表性安全架构是 **感知-计算-控制（Perception-Compute-Control, PPC）**，它对感知、推理、后处理的**最坏执行时间（WCET）做上界约束**，以满足 ISO 13849-1 的功能安全时序要求——本质是**把「概率性的 AI 性能」转化为「有保证的安全时序」**。这是 AI 进工业产线时必须过的门槛：AI 可以不确定，但安全停机/响应的时间必须确定。

### 4. 传感是基础，不是算力

架构分层往往被理解为「从高性能计算开始」，但实际是**「从传感器边缘开始」**：感知/边缘调理 → 感知/AI → 控制/执行 → 数据/分析。同步的多模态传感融合，是喂给上层智能环的根基。

### 5. 人机混合（Human-in-the-Loop）的变体

并非所有场景都要全自主。AR 辅助 + 大模型的方案里，**空间感知由人承担，推理/规划由 LLM 承担**，形成「人类感知 + 人机混合决策」范式——避免把昂贵领域知识强行灌进 LLM，还能提高可靠性。工业落地里「人在环」是实用的兜底选择。

## 适用场景

AI 机器人单元的顶层架构设计、边缘部署选型、实时与功能安全边界评估；为 K4P 里「数字孪生」「Isaac 管线」「实时对准」等文档提供架构视角。

## 参考资料

1. [LLM-Guided Safety Agent for Edge Robotics with an ISO-Compliant Perception-Compute-Control Architecture](https://arxiv.org/abs/2604.20193)
2. [Edge-intelligent vision-based robotic manipulation for real-time pick-and-place in dynamic industrial environments](https://link.springer.com/article/10.1038/s41598-026-62645-6)

<!-- self_check: K4B_20260829_003 ✓ ①②③④⑤⑥⑦ -->
