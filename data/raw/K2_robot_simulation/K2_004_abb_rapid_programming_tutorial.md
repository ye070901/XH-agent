# ABB RAPID 机器人编程完整教程（2026 版含实战代码）

- **来源**：https://plcprogramming.io/blog/abb-robot-programming-tutorial
- **作者/机构**：PLC Programming IO（国际自动化技术教育平台）
- **日期**：2026-03
- **权威等级**：B
- **领域标签**：K2_RAPID编程
- **摘要**：涵盖 RAPID 语言全部核心要素：PROC/FUNC/TRAP 三类程序结构与模块化编程、robtarget/jointtarget/speeddata/zonedata/tooldata/wobjdata 七大数据类型详解、MoveJ/MoveL/MoveC 三大运动指令及速度/转弯半径参数配置。含完整可运行的搬运+机床上下料示例程序（含 WaitDI 超时保护、Offs() 偏移计算），代码可直接导入 RobotStudio 仿真验证。

---

## 正文

### 一、RAPID 语言概述

RAPID（Robot Application Programming Interactive Domain）是 ABB 所有工业机器人的专有高级编程语言，运行于 IRC5 或 OmniCore 控制器。程序由 **模块（Module）** → **例行程序（Routine）** → **指令（Instruction）** 三级结构组成。

### 二、三种例行程序类型

| 类型 | 关键字 | 返回值 | 典型用途 |
|------|--------|--------|----------|
| 过程 | `PROC` | 无 | 主程序、运动序列、逻辑控制 |
| 函数 | `FUNC` | 有（任意类型） | 数学计算、状态判断、坐标变换 |
| 中断 | `TRAP` | 无 | 硬件信号响应、急停处理、错误恢复 |

**示例**：
```rapid
PROC main()
    MoveJ pHome, v500, z50, tGripper;
    PickPart;
    PlacePart;
ENDPROC

FUNC num CalcOffset(num base, num increment)
    RETURN base + increment;
ENDFUNC

TRAP EmergencyStop
    StopMove;
    ResetError;
ENDTRAP
```

### 三、核心数据类型

#### 3.1 robtarget（机器人目标点）

定义 TCP 在空间中的完整位姿：

```rapid
CONST robtarget pPickPos := [
    [500, 200, 50],           ! 位置 X, Y, Z (mm)
    [0.707107, 0, 0.707107, 0], ! 姿态四元数 q1, q2, q3, q4
    [0, 0, 0, 0],             ! 轴配置 cf1, cf4, cf6, cfx
    [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]  ! 外轴位置
];
```

四元数与欧拉角转换：
- `[1, 0, 0, 0]` → 姿态与世界坐标系对齐
- `[0.707, 0, 0.707, 0]` → 绕 Z 轴旋转 90°

#### 3.2 speeddata（速度数据）

```rapid
CONST speeddata vFast := [2000, 500, 5000, 1000];  ! 自定义速度
! 预定义速度：v5, v10, v20, v50, v100, v200, v300, v500, v800, v1000, v1500, v2000
```

| 字段 | 含义 | 单位 |
|------|------|------|
| v_tcp | TCP 线速度 | mm/s |
| v_ori | 姿态旋转速度 | °/s |
| v_leax | 线性外轴速度 | mm/s |
| v_reax | 旋转外轴速度 | °/s |

#### 3.3 zonedata（转弯半径/区域数据）

```rapid
! fine = 精确到位（机器人完全停止再执行下一条，用于焊接/取放料）
! z1 ~ z200 = 平滑过渡半径 1~200mm（用于快速移动、缩短节拍）

MoveL p1, v500, fine, tGripper;   ! 精确停止于 p1
MoveL p2, v500, z10, tGripper;    ! 距 p1 10mm 处开始向 p2 转弯过渡
```

#### 3.4 tooldata（工具数据）

```rapid
PERS tooldata tWeldTorch := [
    TRUE,                         ! 是否已定义
    [[0, 0, 200], [1, 0, 0, 0]],  ! TCP 位置与姿态（相对法兰）
    [1.5, [0, 0, 80], [1, 0, 0, 0], 0, 0, 0]  ! 负载数据
];
```

TCP 标定操作（5 点法）：
1. 在示教器或 RobotStudio 中开始 TCP 标定
2. 以工具尖端触碰同一固定点 4 次（每次不同姿态）→ 确定 TCP 位置
3. 第 5 次沿 Z 方向移动 → 确定 TCP Z 轴方向
4. 误差 < 2mm → 标定成功

#### 3.5 wobjdata（工件坐标数据）

```rapid
PERS wobjdata wPallet := [
    FALSE, TRUE, "",               ! 机器人持有/固定/移动轨道
    [[800, 300, 0], [1, 0, 0, 0]], ! 用户坐标系原点与姿态
    [[0, 0, 0], [1, 0, 0, 0]]      ! 目标坐标系（相对用户坐标）
];
```

### 四、三大运动指令详解

| 指令 | 运动类型 | 路径 | 速度参考 | 适用场景 |
|------|----------|------|----------|----------|
| `MoveJ` | 关节插补 | 不可预测（弧线） | 关节速度 % | 快速定位、Home 返回 |
| `MoveL` | 直线插补 | 直线 | TCP 速度 mm/s | 焊接、取放料、精确插入 |
| `MoveC` | 圆弧插补 | 圆弧 | TCP 速度 mm/s | 圆弧焊缝、绕圆柱运动 |

```rapid
! MoveJ 示例 — 快速回到 Home
MoveAbsJ [[0,0,0,0,30,0],[9E9,9E9,9E9,9E9,9E9,9E9]], v500, z50, tGripper;

! MoveL 示例 — 直线接近取料点
MoveL pPickPos, v100, fine, tGripper \WObj:=wConveyor;

! MoveC 示例 — 圆弧焊缝
MoveC pAuxPoint, pEndPoint, v50, fine, tWeldTorch \WObj:=wWeldTable;
```

### 五、IO 信号与流程控制

#### 5.1 数字 IO 操作

```rapid
SetDO DO_Gripper, 1;                         ! 设置输出为高（夹紧）
SetDO DO_Gripper, 0;                         ! 设置输出为低（松开）
PulseDO \PLength:=0.5, DO_Conveyor;          ! 0.5 秒脉冲触发输送带
WaitDI DI_PartReady, 1;                      ! 等待输入信号为高
WaitDI DI_PartReady, 1 \MaxTime:=30 \TimeFlag:=bTimeout;  ! 带超时的等待（防死锁）
```

#### 5.2 流程控制

```rapid
! 条件判断
IF bTimeout THEN
    TPWrite "Timeout waiting for part — check conveyor";
    RETURN;
ENDIF

! 循环
FOR i FROM 0 TO 4 DO
    MoveL pPositions{i}, v200, z10, tGripper;
ENDFOR

WHILE nCount < 10 DO
    PickAndPlace;
    nCount := nCount + 1;
ENDWHILE
```

### 六、完整搬运程序示例

```rapid
MODULE PickAndPlace
    ! === 工具与工件坐标 ===
    PERS tooldata tGripper := [TRUE, [[0,0,100],[1,0,0,0]], [2,[0,0,50],[1,0,0,0],0,0,0]];
    PERS wobjdata wPickTable := [FALSE,TRUE,"",[[500,200,0],[1,0,0,0]],[[0,0,0],[1,0,0,0]]];
    PERS wobjdata wPlaceTable:= [FALSE,TRUE,"",[[800,400,0],[1,0,0,0]],[[0,0,0],[1,0,0,0]]];

    ! === 目标点 ===
    CONST robtarget pHome   := [[600,0,800],[0.707,0,0.707,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];
    CONST robtarget pPick   := [[500,200,30],[0.707,0,0.707,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];
    CONST robtarget pPlace  := [[800,400,30],[0.707,0,0.707,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];

    VAR bool bTimeout := FALSE;
    VAR num nCycleCount := 0;

    PROC main()
        MoveAbsJ pHome, v500, z50, tGripper;
        WHILE nCycleCount < 20 DO
            PickPart;
            PlacePart;
            nCycleCount := nCycleCount + 1;
            TPWrite "Cycle " \Num:=nCycleCount \Write;
        ENDWHILE
    ENDPROC

    PROC PickPart()
        WaitDI DI_PartReady, 1 \MaxTime:=30 \TimeFlag:=bTimeout;
        IF bTimeout THEN
            TPWrite "Timeout — waiting for part";
            RETURN;
        ENDIF
        MoveJ Offs(pPick, 0, 0, 200), v500, z10, tGripper \WObj:=wPickTable;
        MoveL pPick, v100, fine, tGripper \WObj:=wPickTable;
        SetDO DO_Gripper, 1;
        WaitTime 0.3;
        MoveL Offs(pPick, 0, 0, 200), v200, z10, tGripper \WObj:=wPickTable;
    ENDPROC

    PROC PlacePart()
        MoveJ Offs(pPlace, 0, 0, 200), v500, z10, tGripper \WObj:=wPlaceTable;
        MoveL pPlace, v100, fine, tGripper \WObj:=wPlaceTable;
        SetDO DO_Gripper, 0;
        WaitTime 0.2;
        MoveL Offs(pPlace, 0, 0, 200), v200, z10, tGripper \WObj:=wPlaceTable;
    ENDPROC
ENDMODULE
```

### 七、Offs() 偏移函数详解

`Offs()` 是 RAPID 码垛编程的核心函数，在当前工件坐标系下对目标点进行平移：

```rapid
! Offs(target, dx, dy, dz)
pTarget := Offs(pBase, i*80, j*100, k*200);
! 在工件坐标系 X 方向偏移 80mm×i，Y 偏移 100mm×j，Z 偏移 200mm×k

! 码垛三层每层 5×4 个箱子
FOR k FROM 0 TO 2 DO
    FOR i FROM 0 TO 4 DO
        FOR j FROM 0 TO 3 DO
            pPos := Offs(pPalletOrigin, i*120, j*100, k*150);
            MoveJ Offs(pPos, 0, 0, 200), v500, z10, tGripper;
            MoveL pPos, v100, fine, tGripper;
            SetDO DO_Gripper, 0;
            MoveL Offs(pPos, 0, 0, 200), v200, z10, tGripper;
        ENDFOR
    ENDFOR
ENDFOR
```

## 适用场景

- **Agent2 知识生成**：生成搬运/码垛 RAPID 程序模板时作为核心参考
- **RAG 检索**：匹配"RAPID MoveJ MoveL 区别""zonedata 怎么设置""Offs 函数怎么用""TCP 标定步骤"等查询
- **学情诊断**：判断用户对 RAPID 语法和机器人编程范式的掌握程度

<!-- self_check: K2_20260804 ✓ ①②③④⑤⑥⑦ -->
