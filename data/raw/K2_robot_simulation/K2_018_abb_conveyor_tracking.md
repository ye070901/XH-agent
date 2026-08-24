# ABB 输送带跟踪 Conveyor Tracking 配置

- **来源**：https://search.abb.com/library/Download.aspx?DocumentID=3HAC066561-001&LanguageCode=en
- **作者/机构**：ABB Robotics
- **日期**：2022-03-01
- **权威等级**：A
- **领域标签**：K2_RobotStudio仿真
- **摘要**：输送带跟踪（Conveyor Tracking）让机器人跟随运动中的传送带抓取工件。本文基于 ABB 官方应用手册，讲解编码器与触发传感器配置、坐标系参数标定、RAPID 跟踪程序编写，以及仿真中的常见故障排查，适用于高速分拣与搬运场景。

---

## 正文

输送带跟踪技术用于机器人对**运动中**的工件进行作业，核心是通过**编码器**实时测量输送带位移，配合**触发传感器**（通常为光电开关）锁存工件位置，再由控制器动态补偿机器人运动。

### 一、硬件与选项前置条件

1. 控制器需安装 **Conveyor Tracking** 选项（无此选项时 `CNV` 相关指令与参数不可见）。
2. 输送带上安装 **增量式正交编码器**（A/B 相，5VDC 或 24VDC），接入对应 IO 板（如 DSQC 652/377 或 OmniCore 的 DSQC2000）。
3. 配置**触发传感器**：工件经过时产生一次脉冲，用于锁存"此刻工件在输送带上的坐标"。

### 二、关键参数配置

在 RobotStudio 的 `Configuration → Motion → Conveyor Encoder Unit` 中设置：

| 参数 | 典型值 | 说明 |
|------|--------|------|
| Minimum Distance | -600 mm | 跟踪窗口下界，覆盖机器人上游需为负 |
| Maximum Distance | 2030 mm | 跟踪窗口上界 |
| Start Window Width | 300 mm | 工件可被锁存的起始窗口宽度 |
| Sync Separation | 100 mm | 相邻工件最小间隔 |
| Counts Per Meter | 由标定得出 | 编码器每米脉冲数 |
| Queue Tracking Distance | 按需 | 排队跟踪距离 |

### 三、标定流程（官方推荐顺序）

1. 确认编码器安装与信号方向正确（旋转方向与输送带运动方向一致）。
2. 标定 `CountsPerMeter`：让输送带走一段已知距离，记录脉冲数，换算每米脉冲数。
3. 标定**输送带基坐标系** `wobjcnv1`：方向需与输送带运动方向一致。
4. 定义 Start Window 与 Sync Separation。
5. 设置 `Adjustment Speed`（机器人追料速度，通常为输送带速度的 130% 左右）。

### 四、RAPID 跟踪程序示例

```rapid
MODULE ConveyorTrack
    PROC main()
        ActUnit CNV1;                 ! 激活输送带跟踪单元
        WHILE TRUE DO
            WaitWObj wobjcnv1;        ! 等待并锁存输送带上的工件
            MoveL p_approach, v1500, z50, tool_grip\WObj:=wobjcnv1;
            MoveL p_pick, v500, fine, tool_grip\WObj:=wobjcnv1;
            SetDO do_grip, 1;
            WaitTime 0.3;
            MoveL p_lift, v500, z50, tool_grip\WObj:=wobjcnv1;
            DropWObj wobjcnv1;        ! 结束对该工件的跟踪
            MoveL p_place, v1000, fine, tool_grip;
            SetDO do_grip, 0;
        ENDWHILE
    ENDPROC
ENDMODULE
```

> 关键点：`wobjcnv1` 需设为 `ufprog = FALSE`（可动用户坐标系）、`ufmec = CNV1`。

### 五、仿真与故障排查

- **机器人追不上工件**：增大 `Adjustment Speed`（上限可到 500%），或降低输送带速度。
- **报警 50082（减速限制）**：增大 `Path Resolution` 或降低 CPU 负载。
- **队列跟踪距离为 0**：若机器人装在轨道上，需正确设置 `Linked Mechanical Unit`，否则最小距离参数被忽略。

## 适用场景

适用于 XH-agent 中"输送带跟踪怎么配""机器人追不上传送带"等故障排查类问题的检索回答，也是搬运/分拣工艺包的核心知识。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
