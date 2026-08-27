# ABB PROFIsafe 扫描器 PLC 集成

- 来源 URL：[ABB Collaborative Speed Control 应用手册](https://library.e.abb.com/public/87333ca1982142e8a7a2c0ed5f944161/3HAC091309%20AM%20Collaborative%20Speed%20Control%20add-in-en.pdf?x-sign=v5pc2U3cOMO2sPX1kfUKhEs2UFQdS2DoDFRwq4vSY3M8zy0pXnzVE1kjWCGR%2B1uF)
- 作者/机构：ABB Robotics；本文由 XH-agent 基于官方资料二次整理
- 发布日期：2024；本文整理日期 2026-08-27
- 来源权威等级：A
- 内容性质：基于官方资料的中文二次整理，非逐字原文
- 领域标签：K3_产线适配 / 产线集成与 PLC
- 摘要：整理 ABB 机器人、PLC 与 PROFINET/PROFIsafe 激光扫描器的地址、设备描述文件、保护区和安全配置写入流程，适用于人机共域或限速协作单元的联调。

---

## 正文

### 1. 系统职责

ABB 的应用手册给出由 PLC 作为主站、通过 PROFIsafe 接入激光扫描器和机器人控制器的配置示例。扫描器的保护区决定人员接近时的速度限制或停止条件；PLC、扫描器与控制器需要使用匹配的网络配置。此类方案属于功能安全应用，实际设计必须由具备资格的人员根据风险评估、控制器版本和安全选件完成验证。

### 2. 组态操作步骤

```text
1. 确认 PLC 支持 PROFIsafe，并核对机器人和扫描器的软件、GSDML 版本。
2. 将控制器和扫描器接入规划网络，为每台设备分配唯一 IP、PROFINET 站名和 F-destination 地址。
3. 在扫描器配置工具中定义保护区、监控工况与安全输入输出来源。
4. 在 PLC 工程导入机器人与扫描器的设备描述文件，配置安全 I/O 的源/目的地址和过程数据长度。
5. 下载配置后，按 ABB 安全配置流程写入控制器并重启；不得仅修改 PLC 而跳过控制器侧配置。
6. 低速验证每个保护区触发时的减速、停止、报警、复位和恢复节拍。
```

### 3. 验收点

每台扫描器必须有不同的 IP、站名和 F-destination 地址，且 PLC 工程中的设备描述、地址和机器人安全配置相一致。验证不应只看普通 I/O 是否通信，还应确认安全 I/O 的诊断状态、监视超时和安全停止实际生效。测试记录应覆盖遮挡保护区、网络断开、重新上电和受控复位。

### 4. 禁止做法

禁止用普通 PLC 位模拟安全输入，也不能以临时旁路维持生产。保护区大小、速度阈值、F 地址或安全逻辑任一项变化，都属于安全功能变更，需重新评估并按现场程序验证。

## 适用场景

适用于 ABB RobotWare 7 及支持 PROFIsafe 的协作限速、激光扫描器保护和 PLC 安全接口项目。

## 参考资料

1. [ABB Collaborative Speed Control 应用手册](https://library.e.abb.com/public/87333ca1982142e8a7a2c0ed5f944161/3HAC091309%20AM%20Collaborative%20Speed%20Control%20add-in-en.pdf?x-sign=v5pc2U3cOMO2sPX1kfUKhEs2UFQdS2DoDFRwq4vSY3M8zy0pXnzVE1kjWCGR%2B1uF)。

<!-- self_check: K3_20260827 ✓ ①②③④⑤⑥⑦ -->
