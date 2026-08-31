# 核心术语与概念速查：手眼标定、Sim-to-Real、数字孪生、ROS 2

- 来源 URL：[Hand/Eye calibration of Robot arms — KoreaScience](http://koreascience.kr/article/CFKO200011921905912.page)；[Reinforcement learning in robotic systems: A review on sim-to-real transfer — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0921889025004245)；[ROS 2 in a Nutshell: A Survey — ACM Computing Surveys](https://dl.acm.org/doi/10.1145/3815113)；[Virtual Commissioning Evolves into a Model-driven Digital Twin — ARC](https://www.arcweb.com/blog/virtual-commissioning-evolves-model-driven-digital-twin)
- 作者/机构：KoreaScience / ScienceDirect / ACM / ARC Advisory Group；本文由 XH-agent 基于公开资料二次整理
- 发布日期：2025；本文整理日期 2026-08-29
- 来源权威等级：B
- 内容性质：多来源公开文献的中文概念归纳；术语定义为通用学术共识，非单一厂商表述
- 领域标签：K4B_术语速查
- 摘要：用一页式条目解释「AI + 工业机器人」最高频的几个术语——手眼标定（AX=XB）、Sim-to-Real 与现实鸿沟、数字孪生与虚拟调试、ROS 2 的节点/话题/服务/DDS。供快速建立概念地图，再深入对应实操文档。

---

## 正文

### 1. 手眼标定（Hand-Eye Calibration）

确定**相机坐标系与机器人坐标系之间刚体变换**（旋转 + 平移）的过程，是视觉引导抓取、视觉伺服、三维重建的前提。

核心数学形式是齐次矩阵方程：

```text
AX = XB
```

`A`、`B` 是机器人/相机在两处位姿间的相对运动，`X` 是待求的手眼变换。两种配置：

- **Eye-in-Hand（眼在手上）**：相机固定在机器人末端，标定目标是求相机相对末端的位姿；
- **Eye-to-Hand（眼在手外）**：相机固定在外（如支架），标定目标是求相机相对机器人基座的位姿。

解法从早期的 **Shiu & Ahmad（1989）、Tsai & Lenz（1989）** 把旋转/平移分离求解，发展出四元数/对偶四元数法、Kronecker 积 + SVD 联立法、全局最优符号法等。为保证唯一解，通常需要**至少两组相对运动**；精度受输入噪声、机器人定位误差、视觉测量误差影响。

### 2. Sim-to-Real 与现实鸿沟（Reality Gap）

**Sim-to-Real 迁移**指把在仿真里训练好的强化学习（RL）策略部署到真实机器人。核心问题是**现实鸿沟**：仿真的物理动力学、传感输入、环境变异性、建模误差、传感器噪声、物体物理属性，与真实世界存在偏差，导致策略迁移后性能下降甚至失败。

最常用的弥合手段是**域随机化（Domain Randomization, DR）**：训练时随机化仿真参数（环境与机器人自身），让策略对真实世界的变异鲁棒。关键教训：

- **仿真成功率不可靠地预测真实表现**——某推挤任务里，仿真成功率最低（67%，因 DR）的策略反而是唯一能真实部署的（真实 80%）；
- 常规 DR 常**遗漏静摩擦**等参数，导致真实欠性能，需要「静摩擦感知的域随机化」；
- DR 有**泛化 vs 专用**的权衡，接触密集任务可能对分布外配置失败。

更先进的方向包括**悲观域随机化（带安全保证）**、**上下文感知策略**（条件化于质量/摩擦等估计参数）、以及用少量真实数据校正性能的框架。

### 3. 数字孪生与虚拟调试

**数字孪生（Digital Twin）** 是**与物理实体实时连接、数据双向流动的虚拟表示**——不只是「长得像」，而是「行为像」，具备准确运动学、物理模型与实时反馈回路。区别于单向数据流的「数字阴影（digital shadow）」。

**虚拟调试（Virtual Commissioning, VC）** 是在物理实施之前，用数字孪生对制造系统做仿真与测试验证，让 PLC 代码、机器人程序在硬件到位前就能并行开发与调试。相关方法链：

- **MiL（Model-in-the-Loop）**：逻辑模型接仿真模型；
- **SiL（Software-in-the-Loop）**：软件代码跑逻辑模型；
- **HiL（Hardware-in-the-Loop）**：真实控制器对虚拟产线模型测试。

典型工作流：概念设计 → 仿真分析 → 虚拟调试 → 执行。机器人是数字孪生/VC 的核心应用（如 ABB RobotStudio、西门子 Process Simulate）。相关标准：ISO/IEC 30173:2023（数字孪生概念与术语）、ISO 23247:2021（制造数字孪生框架）。

### 4. ROS 2 核心概念

**ROS 2** 是构建机器人应用的一套库与工具，底层由 **DDS（Data Distribution Service）** 中间件支撑，采用**去中心化自动发现**（区别于 ROS 1 的中心化 ROS Master），无单点故障。

| 概念 | 说明 |
|------|------|
| **节点（Node）** | 独立进程/组件，做一件具体计算（驱动、感知、控制），可跨语言/跨机器 |
| **话题（Topic）** | 异步发布/订阅，适合连续流式数据（传感、状态、速度指令） |
| **服务（Service）** | 同步请求/响应（客户端-服务器），适合即时查询 |
| **动作（Action）** | 长任务 + 目标/反馈/取消，适合「移动到某点」这类长时任务 |
| **QoS** | 服务质量策略（可靠性、持久性、历史深度、截止时间），适配延迟/带宽/可靠性 |
| **RMW** | 中间件抽象，支持 FastDDS / CycloneDDS / Connext 等多家 DDS |

**实时性**方面，ROS 2 靠 QoS 策略 + PREEMPT_RT 内核、CPU 隔离、内存锁、固定频率发布等手段改善；进程内节点可零拷贝通信降低延迟。ROS 1 → ROS 2 的关键变化：发现机制（Master → DDS）、通信（自定义 TCP/UDP → DDS）、实时与安全性均有提升。

## 适用场景

快速建立「AI + 工业机器人」概念地图；阅读 K4P 实操文档（手眼标定、Isaac Lab Sim2Real、RobotStudio 虚拟调试、ROS 2 实时接口）前的术语铺垫。

## 参考资料

1. [Hand/Eye calibration of Robot arms with a 3D visual sensing system](http://koreascience.kr/article/CFKO200011921905912.page)
2. [Reinforcement learning in robotic systems: A review on sim-to-real transfer](https://www.sciencedirect.com/science/article/abs/pii/S0921889025004245)
3. [ROS 2 in a Nutshell: A Survey](https://dl.acm.org/doi/10.1145/3815113)
4. [Virtual Commissioning Evolves into a Model-driven Digital Twin — ARC](https://www.arcweb.com/blog/virtual-commissioning-evolves-model-driven-digital-twin)

<!-- self_check: K4B_20260829_004 ✓ ①②③④⑤⑥⑦ -->
