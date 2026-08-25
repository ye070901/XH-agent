# FANUC ROBOGUIDE WeldPRO 焊接仿真

- **来源**：http://www.fanuc.co.jp/en/product/catalog/pdf/Roboguide(E)_v04_s.pdf
- **作者/机构**：FANUC CORPORATION
- **日期**：2023-07-15
- **权威等级**：A
- **领域标签**：K2_焊接工艺包
- **摘要**：WeldPRO 是 FANUC ROBOGUIDE 的弧焊专用仿真插件，支持 CAD-to-Path 自动生成焊接轨迹、多层多道、摆动与寻位传感仿真。本文介绍焊接工作单元搭建、CAD-to-Path 编程、焊缝姿态调整与真机导出流程，帮助离线完成弧焊程序开发。

---

## 正文

WeldPRO 把 FANUC 弧焊机器人的编程搬到 3D 虚拟环境中，其核心是 **CAD-to-Path**：直接点选 CAD 模型的焊缝边线，自动生成 TP 程序与焊接姿态，大幅缩短示教时间。

### 一、焊接工作单元搭建

1. 在 ROBOGUIDE 中新建弧焊工作单元，选择机器人型号（如 ARC Mate 100iD）与软件版本。
2. 勾选 **ArcTool** 焊接选项与 **WeldPRO** 功能。
3. 导入焊枪工具、工件 CAD、变位机与周边设备。
4. 配置焊接参数数据集（Schedule）：电流、电压、送丝速度、摆动参数。

### 二、CAD-to-Path 自动编程

1. 点击 WeldPRO 工具栏的「CAD-to-Path」。
2. 在工件模型上**点选焊缝边线**，系统自动沿边线生成焊接路径点，并保持焊枪与焊缝的法向夹角。
3. 对复杂曲面，可设置**逼近/离开姿态**、**多层多道偏移**与**摆动（Weave）**参数。
4. 检查路径点的可达性与碰撞，自动生成 TP 程序。

### 三、TP 焊接程序示例

```tp
   1:J P[1] 100% CNT100          ; 焊前安全点
   2:L P[2] 500mm/s CNT50        ; 接近焊缝起点
   3:  Arc Start[1]              ; 起弧（焊接数据集 1）
   4:L P[3] 30cm/min CNT0        ; 焊缝起点（焊接速度 30cm/min）
   5:  Weave Sine[1]             ; 启用正弦摆动
   6:L P[4] 30cm/min CNT0        ; 焊缝终点
   7:  Weave End                 ; 结束摆动
   8:  Arc End[1]                ; 收弧
   9:L P[5] 500mm/s CNT50        ; 离开焊缝
  10:J P[1] 100% CNT100          ; 回安全点
```

### 四、寻位与传感仿真

- **Wire Touch / 寻位（Touch Sensing）**：用焊丝触碰工件定位焊缝起点，WeldPRO 可仿真该过程并修正路径偏移。
- **摆动（Weave）**：支持正弦、三角、梯形摆动模式，仿真中可预览摆动包络。

### 五、真机导出与验证

1. 仿真验证通过后，用 ROBOGUIDE 的「Program Transfer」把 TP 程序下发到真实控制器。
2. 真机先 T1 低速空跑（不引弧）验证轨迹，再启用焊接。
3. 真机需重新标定焊枪 TCP 与用户坐标系（UFRAME）。

### 六、常见问题

| 现象 | 原因 | 对策 |
|------|------|------|
| CAD-to-Path 无路径 | 未正确点选边线 | 重新选边或手动补点 |
| 焊缝姿态异常 | 法向设置错误 | 调整姿态约束参数 |
| 真机轨迹偏移 | TCP/UFRAME 未对齐 | 真机重新标定 |

## 适用场景

本文用于 XH-agent 回答"FANUC 弧焊怎么离线编程""WeldPRO CAD-to-Path 怎么用"等问题，是 K2 FANUC 焊接仿真的核心内容。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
