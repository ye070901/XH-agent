# FANUC ROBOGUIDE 离线编程与工艺包仿真完整指南

- **来源**：https://plcprogramming.io/blog/fanuc-offline-programming-roboguide
- **作者/机构**：PLC Programming IO（结合 FANUC Academy 官方培训资料）
- **日期**：2025-02
- **权威等级**：B
- **领域标签**：K2_FANUC仿真
- **摘要**：全面讲解 FANUC ROBOGUIDE 离线编程仿真平台的核心工作流。涵盖 Workcell 虚拟工作单元创建、虚拟示教器 TP 编程（含位置寄存器 PR 和数值寄存器 R 使用）、碰撞检测与可及性校验、I/O 仿真、程序导出至真实控制器。重点介绍 HandlingPRO（搬运/码垛，含码垛模式向导与视觉引导）、WeldPRO（弧焊/点焊，含焊缝跟踪仿真与焊枪角度校验）、PaintPRO（喷涂厚度仿真）三大工艺包。支持 R-30iB Plus 控制器，最多 20 台虚拟机器人协同仿真。

---

## 正文

### 一、ROBOGUIDE 简介

ROBOGUIDE 是 FANUC 官方的离线编程与仿真软件，其核心优势在于使用**虚拟机器人控制器**——运行的固件与真实 FANUC 控制器完全一致，仿真结果可以直接信任。

| 功能维度 | 说明 |
|----------|------|
| 控制器支持 | R-30iB Plus / R-30iB / R-30iA / R-J3iB |
| 最大虚拟机器人 | 20 台/PC |
| CAD 导入格式 | IGES（含裁剪曲面）、STL、OBJ |
| 导出文件类型 | TP 程序、位置寄存器 PR、数值寄存器 R、字符串寄存器 SR、码垛寄存器、DCS/I/O 配置 |

### 二、完整操作流程

#### 步骤 1：创建 Workcell（虚拟工作单元）

1. 启动 ROBOGUIDE → File → New Cell
2. **选择机器人**：
   ```
   机器人型号：LR Mate 200iD/7L（小型搬运）或 M-20iA/35M（中型）
   控制器版本：R-30iB Plus
   应用类型：HandlingPRO（搬运）/ WeldPRO（焊接）/ PaintPRO（喷涂）
   运动组：1（单机器人）/ 2（+ 外部轴）
   ```
3. **添加选项**：
   - J518 Extended Axis Control（扩展轴控制——导轨/变位机）
   - J601 Multi-Group Motion（多组运动——多机器人协同）
4. 导入周边设备 CAD 模型（夹具、输送带、托盘、变位机）
5. 定位并调整布局——使用 PnP 或手动坐标输入

#### 步骤 2：创建工具与工件坐标系

**工具创建（TCP 定义）**：
1. UTILITIES → Tool Setup
2. 选择真空吸盘/夹爪模型
3. 定义 TCP 位置：工具末端中心，Z 轴指向抓取方向
4. 设置负载：`PayLoad = 2.0kg, Center of Gravity (0, 0, 80)`

**工件坐标系（UFrame）定义**：
1. UTILITIES → Frames → User Frame
2. 3 点法标定：
   - 示教 Orient Origin Point —— 工件台角点
   - 示教 X Direction Point —— 沿 X 方向 > 100mm
   - 示教 Y Direction Point —— 沿 Y 方向 > 100mm

#### 步骤 3：TP 程序编写（虚拟示教器）

FANUC 使用 **TP（Teach Pendant）语言** 编程，核心指令如下：

```
! ===== 运动指令 =====
J P[1] 100% FINE              ; 关节运动到 P[1]，100% 速度，精确定位
L P[2] 500mm/s FINE           ; 直线运动到 P[2]，500mm/s，精确定位
C P[3]                        ; 圆弧运动
    P[4] 500mm/s CNT50        ; 圆弧终点 P[4]，CNT50 平滑过渡

! ===== 位置寄存器 =====
PR[1] = P[1]                  ; 将 P[1] 赋值给位置寄存器 1
PR[2] = PR[1]                 ; 位置寄存器间赋值
PR[2,3] = PR[2,3] + 50       ; Z 方向偏移 50mm（索引 1=X, 2=Y, 3=Z）

! ===== IO 控制 =====
DO[1] = ON                    ; 数字输出 1 为 ON（夹紧）
DO[1] = OFF                   ; 数字输出 1 为 OFF（松开）
WAIT DI[1] = ON               ; 等待数字输入 1 为 ON

! ===== 流程控制 =====
IF (DI[2] = ON) THEN
    CALL PICKPART
ELSE
    WAIT 0.5(SEC)
ENDIF

FOR R[1] = 1 TO 10
    CALL PLACEPART
ENDFOR

! ===== 寄存器 =====
R[1] = 1                      ; 数值寄存器（整数/小数）
R[2] = R[1] + 1
```

#### 步骤 4：码垛程序示例（HandlingPRO）

TP 码垛程序使用位置寄存器的偏移实现层行列循环：

```
! 码垛参数设定
R[10] = 5                     ! 行数
R[11] = 4                     ! 列数
R[12] = 3                     ! 层数
R[13] = 120                   ! 行间距 mm
R[14] = 100                   ! 列间距 mm
R[15] = 150                   ! 层高 mm

! 基准位置
PR[10] = P[10]                ! 托盘原点（底层第一位置）

! 三层码垛循环
FOR R[20] = 0 TO (R[12]-1)
    FOR R[21] = 0 TO (R[11]-1)
        FOR R[22] = 0 TO (R[10]-1)
            ! 计算目标位置
            PR[20] = PR[10]
            PR[20,1] = PR[20,1] + R[22]*R[13]  ! X = 基准X + 列 × 列间距
            PR[20,2] = PR[20,2] + R[21]*R[14]  ! Y = 基准Y + 行 × 行间距
            PR[20,3] = PR[20,3] + R[20]*R[15]  ! Z = 基准Z + 层 × 层高

            ! 放置循环
            J PR[10] 100% CNT50                ! 快速接近（高于目标 200mm）
            PR[20,3] = PR[20,3] + 200
            L PR[20] 250mm/s CNT20             ! 中速靠近
            PR[20,3] = PR[20,3] - 200
            L PR[20] 100mm/s FINE              ! 慢速精确放置
            DO[1] = OFF                         ! 松开夹爪
            WAIT 0.2(SEC)
            L PR[20] 200mm/s CNT50             ! 退离
            PR[20,3] = PR[20,3] + 200
        ENDFOR
    ENDFOR
ENDFOR
```

#### 步骤 5：碰撞检测与仿真验证

1. **启用碰撞检测**：
   - Tools → Collision Detection → Enable
   - 设置 Tolerance = 5mm（安全距离阈值）
   - 选择检测对象对（Robot-Tool-Workpiece）

2. **运行仿真**：
   - 点击 Play → 实时观察机器人运动
   - 碰撞位置红色高亮 → 点击暂停 → 修改路径点
   - Cycle Time 面板显示每个运动段的耗时和总周期

3. **可及性验证**：
   - 选中所有目标点 → Reachability Check
   - 红色 = 不可达 → 调整机器人布局或工件位置
   - 黄色 = 可能奇异 → 检查关节 5 是否接近 0°

#### 步骤 6：程序导出与真机部署

1. File → Export → TP Programs
2. 选择导出文件类型：
   - `.TP` — TP 程序文件
   - `.VR` — 位置寄存器文件
   - `.VR` — 数值寄存器文件
   - `.SV` — 系统变量（一般不导出）
3. 通过 USB/CF 卡/FTP 复制到真实控制器
4. 在 T1 模式下逐行验证 → 确认无误 → 切换到 AUTO 模式

### 三、三大工艺包详解

| 工艺包 | 核心功能 | 适用场景 |
|--------|----------|----------|
| **HandlingPRO** | 码垛模式向导、输送链跟踪设置、视觉引导仿真 | 搬运、码垛、机床上下料 |
| **WeldPRO** | 焊接参数编辑器、焊缝跟踪仿真、焊枪角度校验 | 弧焊、点焊 |
| **PaintPRO** | 喷涂厚度仿真、覆盖率分析、喷枪参数编辑器 | 喷漆、喷粉、涂胶 |

**HandlingPRO Pallet Pattern Wizard**：
1. Tools → Pallet Pattern → Create New
2. 输入 Row × Column × Layer
3. 示教 4 个基准点（同 ABB 4 点法）
4. 自动生成全部码垛位置

**WeldPRO 焊接仿真**：
1. 导入工件 CAD → 定义焊缝（起弧点 + 收弧点）
2. 配置焊接参数：电压/电流/送丝速度/行进速度
3. WeldPRO 自动生成焊接路径和焊枪姿态
4. 模拟焊缝跟踪——验证电弧是否始终对准焊缝中心

### 四、ROBOGUIDE vs RobotStudio 对比

| 对比维度 | ROBOGUIDE | RobotStudio |
|----------|-----------|-------------|
| 机器人品牌 | FANUC | ABB |
| 程序语言 | TP / KAREL | RAPID |
| 虚拟控制器 | 运行真实控制器固件 | 运行真实控制器固件 |
| 运动指令 | J / L / C | MoveJ / MoveL / MoveC |
| 工艺包覆盖 | Handling / Welding / Painting / Dispensing | Palletizing / Welding / Painting / Machining |
| 坐标系数量 | UTOOL(10) + UFRAME(10) | tooldata + wobjdata（不限数量） |

## 适用场景

- **Agent2 知识生成**：FANUC TP 程序模板、码垛循环逻辑参考
- **RAG 检索**：匹配"ROBOGUIDE 怎么用""FANUC TP 编程""PR 位置寄存器偏移""FANUC 码垛程序""HandlingPRO 工艺包"等查询
- **学情诊断**：判断用户是否了解多品牌离线编程软件差异

<!-- self_check: K2_20260804 ✓ ①②③④⑤⑥⑦ -->
