# KUKA.OfficeLite、KUKA.Sim 与 SafeOperation 的验证范围

- **来源**：[KUKA.SystemSoftware](https://www.kuka.com/-/media/kuka-downloads/files/87f2706ce77c4318877932fb36f6002d/kukasystemsoftware-en.pdf)、[KUKA.SafeOperation](https://www.kuka.com/en-de/products/robot-systems/software/hub-technologies/kuka_safeoperation)
- **作者/机构**：KUKA；本文由 XH-agent 基于官方资料整理
- **整理日期**：2026-09-03
- **权威等级**：A
- **领域标签**：K10_KUKA虚拟调试 / K2_仿真
- **摘要**：区分 OfficeLite 虚拟 KSS 控制器、KUKA.Sim 工作站仿真和 SafeOperation 安全功能，给出启动失败时优先收集的版本与日志证据，避免把离线测试等同于安全验收。

---

## 正文

### 1. 三个工具解决不同问题

KUKA 将 OfficeLite 描述为 KUKA.SystemSoftware KSS 的虚拟化版本，适用于在无实体控制器时验证系统软件相关配置和程序。KUKA.Sim 用于单元布局、可达性、碰撞、路径和流程的离线验证。SafeOperation 是受安全相关硬件和软件支持的安全功能，用于监控空间、轴/笛卡尔速度等；其配置与验收不能由一般仿真结果取代。

### 2. OfficeLite/虚拟控制器无法启动时的分诊

1. 记录 OfficeLite、KSS、KUKA.Sim、WorkVisual 和宿主操作系统版本，以及目标机器人/控制器项目版本。
2. 收集启动日志、虚拟机资源/网络配置、许可证或选件状态，不要反复重建后丢失首次失败信息。
3. 核对项目是否包含只适用于真机硬件、现场总线、安全选件或外设驱动的配置；虚拟控制器并不自动具备全部实物接口。
4. 使用最小项目确认虚拟控制器基本启动后，再逐步导入机器人程序、I/O、外轴和工艺包，定位是哪一项配置导致失败。
5. 修复后执行版本一致性、程序检查和离线动作验证；真机仍需按厂商流程进行低速、I/O 与安全功能验证。

### 3. SafeOperation 与坐标/布局的关系

SafeOperation 可以按轴特定或笛卡尔方式定义监控空间，并可考虑工具；工装、工具、基座、外轴和布局变化都会影响原安全空间是否仍然有效。KUKA.Sim 中的 ROBROOT/BASE/TOOL 对齐是工艺仿真的必要条件，但不是 SafeOperation 配置已验证的证据。

### 4. 不能作出的推论

- OfficeLite 可启动，不代表真机现场总线、I/O 或安全选件可以直接上线。
- KUKA.Sim 无碰撞，不代表所有工具扫掠、停止距离和安全空间已经验收。
- 关闭安全配置或删除选件以便虚拟控制器启动，不可作为生产恢复方法。

<!-- self_check: K2_20260903 ✓ OfficeLite ✓ KUKA.Sim ✓ SafeOperation ✓ virtual-boundary -->
