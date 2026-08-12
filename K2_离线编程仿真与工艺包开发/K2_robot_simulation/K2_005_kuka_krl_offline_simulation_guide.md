# KUKA KRL 离线编程与仿真集成技术全解析

- **来源**：https://wenku.csdn.net/doc/bb5wzc7z9y1a
- **作者/机构**：CSDN 技术社区（汇编自 KUKA 官方文档与一线工程师实践）
- **日期**：2024-11
- **权威等级**：B
- **领域标签**：K2_KRL编程
- **摘要**：系统讲解 KUKA KRL 编程语言与离线仿真工具链。涵盖 OrangeEdit 离线编辑器编写 .SRC/.DAT 文件、KUKA.Sim 3D 仿真环境与碰撞检测、KUKA.OfficeLite 虚拟控制器、RoboDK 第三方 OLP 集成。详解 WORLD/ROBROOT/BASE/TOOL 五大坐标系标定（3 点法 BASE + 4 点法 TCP）、PTP/LIN/CIRC 运动指令与逼近参数（C_PTP/C_DIS）、E6POS 位置数据结构、CAD-机器人坐标转换方法。含完整可运行的 .SRC + .DAT 配对代码。

---

## 正文

### 一、KUKA 离线编程工具链

| 工具 | 类型 | 核心功能 |
|------|------|----------|
| **OrangeEdit** | 免费离线编辑器 | 编写 .SRC/.DAT 文件，语法高亮，离线调试 |
| **KUKA.Sim** | 官方仿真平台 | 3D 虚拟环境、路径规划、碰撞检测、RL 代码生成 |
| **KUKA.OfficeLite** | 虚拟控制器 | 完整 KSS 虚拟控制器，程序可无缝迁移至真机 |
| **KUKA.WorkVisual** | 工程配置工具 | 项目管理、IO 配置、总线拓扑、安全配置 |
| **RoboDK** | 第三方 OLP | 支持多品牌机器人后处理，CAD 导入生成路径 |

### 二、KRL 程序结构：.SRC 与 .DAT 文件

每个 KRL 程序必须包含一对同名文件：

**.SRC（源文件）** — 可执行代码：
```kuka
DEF PickAndPlace()
  ; 初始化
  GLOBAL INTERRUPT DECL 3 WHEN $STOPMESS==TRUE DO IR_STOP()
  $BASE = BASE_DATA[1]
  $TOOL = TOOL_DATA[1]
  BAS(#VEL_PTP, 100)
  BAS(#ACC_PTP, 100)

  ; 主循环
  LOOP
    PICK_PART()
    PLACE_PART()
  ENDLOOP
END
```

**.DAT（数据文件）** — 变量声明和初始值：
```kuka
DEFDAT PickAndPlace
  DECL PDAT PPDAT1 = {VEL 100, ACC 100, APO_DIST 50}
  DECL PDAT CPDAT1 = {VEL 2.0, ACC 100, APO_DIST 50}
  DECL FDAT FTOOL1 = {TOOL_NO 1, BASE_NO 1, IPO_FRAME #BASE}
  DECL E6POS P_HOME = {X 0, Y 0, Z 800, A 0, B 0, C 0, S 2, T 10}
  DECL E6POS P_PICK = {X 500, Y 200, Z 50, A 0, B 90, C 0, S 2, T 10}
  DECL E6POS P_PLACE= {X 800, Y 400, Z 50, A 0, B 90, C 0, S 2, T 10}
ENDDAT
```

### 三、五大坐标系系统

| 坐标系 | KRL 名称 | 原点 | 用途 |
|--------|----------|------|------|
| $WORLD | 世界坐标 | 机器人底座 | 全局参考，一般不用于编程 |
| $ROBROOT | 机器人根坐标 | 安装面 | 与 WORLD 相同（除非机器人安装在轨道/高架） |
| $BASE | 基坐标 | 用户定义 | **编程基准坐标系**，通常设在工作台/夹具上 |
| $TOOL | 工具坐标 | TCP | 定义工具中心点和姿态 |
| $FLANGE | 法兰坐标 | 机器人法兰面 | 原始参考，无工具偏移 |

**BASE 坐标系 3 点标定法**：
1. 示教原点（ORG）：将 TCP 移至工件坐标系原点
2. 示教 X 轴正方向点（XX）：沿期望 X 方向移动 > 100mm
3. 示教 Y 轴正方向点（XY）：沿期望 Y 方向移动（决定 XY 平面）
4. 控制器自动计算坐标系矩阵

**TOOL 坐标系 4 点标定法（XYZ-4 点法）**：
1. 以 4 种不同姿态将工具尖端触碰同一固定参考点
2. 控制器解算 TCP 位置（XYZ）
3. 再用 ABC-World 法确定姿态方向

### 四、三种运动指令

| 指令 | 轨迹 | 速度单位 | 逼近方式 | 适用场景 |
|------|------|----------|----------|----------|
| `PTP` | 点到点（关节空间） | `$VEL_AXIS[1..6]` 百分比 | `C_PTP` | 快速定位、无碰撞区域 |
| `LIN` | 直线（笛卡尔空间） | `$VEL.CP` m/s 或 mm/s | `C_DIS` | 焊接、取放、精确接近 |
| `CIRC` | 圆弧 | `$VEL.CP` | `C_DIS` | 圆形焊缝、圆弧轨迹 |

**逼近（Blending）参数使用**：
```kuka
PTP P1 C_PTP           ; PTP 逼近，在上一段轨迹末端加速过渡
LIN P2 C_DIS           ; 按距离逼近，距离上一目标点 d 时开始过渡
LIN P3 CONT            ; 仅姿态逼近（位置精确到位）

! 带速度设置的运动指令
PTP P_HOME Vel=100 % PDAT1        ; 100% 关节速度
LIN P_PICK Vel=0.1 m/s CPDAT1     ; 100mm/s TCP 速度
LIN P_WELD Vel=0.008 m/s CPDAT1   ; 8mm/s 焊接速度
```

### 五、E6POS 位置数据结构

```kuka
DECL E6POS P1 = {
    X 500.0,    ! X 坐标 (mm)
    Y 200.0,    ! Y 坐标 (mm)
    Z 300.0,    ! Z 坐标 (mm)
    A 0.0,      ! 绕 Z 旋转 (°)
    B 90.0,     ! 绕 Y 旋转 (°)
    C 0.0,      ! 绕 X 旋转 (°)
    S 2,        ! Status（轴配置状态位）
    T 10        ! Turn（轴圈数信息）
}
```

**S 和 T 参数**（决定机器人到达该点的关节配置）：
- S（Status）：6 位二进制编码，定义每个轴的正反方向
- T（Turn）：编码每个轴的旋转圈数
- 错误设置 S/T → 机器人可能以完全不同的姿态到达同一位置，甚至无法到达

### 六、IO 信号与逻辑控制

```kuka
! 信号声明（在 .DAT 中）
SIGNAL GI_GRIPPER $OUT[1]       ; 输出信号绑定
SIGNAL GO_CONVEYOR $OUT[2]
SIGNAL SI_PART_READY $IN[3]     ; 输入信号绑定

! 在 .SRC 中使用
GI_GRIPPER = TRUE                ; 夹爪夹紧
WAIT SEC 0.3                     ; 等待 0.3 秒
WAIT FOR SI_PART_READY == TRUE TIMEOUT 30 ; 带超时的信号等待

! 逻辑控制
IF SI_PART_READY == TRUE THEN
  PICK()
ELSE
  WAIT SEC 0.5
ENDIF

FOR nIdx = 1 TO 10
  PTP P_POS[nIdx]
ENDFOR
```

### 七、KUKA.Sim 离线仿真工作流

**步骤 1 — 工作单元建模**：
1. 启动 KUKA.Sim → 新建项目
2. 导入机器人模型（KR 6 R900、KR 10 R1100 等）
3. 导入 STEP/IGES 格式的周边设备（夹具、输送带、变位机）
4. 导入 WRL 格式工件模型

**步骤 2 — 坐标系定义**：
1. 在 3D 视图中定义 BASE 坐标系（与真实工作台一致）
2. 加载 TOOL 模型并定义 TCP
3. 使用 3 点法确认 BASE 原点、X 方向、Y 方向

**步骤 3 — 路径编程**：
1. 在工件表面捕捉目标点（边线中点、圆心等）
2. 生成路径 → 自动填充 PTP/LIN 指令
3. 手动调整焊枪/工具姿态角（A/B/C）
4. 配置每条路径的速度和逼近参数

**步骤 4 — 碰撞检测与验证**：
1. 启用碰撞检测（设置安全距离阈值）
2. 运行完整周期仿真
3. 红色高亮显示碰撞位置 → 修改路径或机器人姿态
4. 检查奇异点（机器人完全伸直时轴 5 为 0）→ 调整目标点位姿

**步骤 5 — KRL 代码导出**：
1. 选择目标控制器型号（KRC4/KRC5）
2. 导出 → 生成 .SRC + .DAT 文件对
3. 通过 USB/网络拷贝到真实控制器 → 在 T1 模式下低速验证

### 八、CAD 到机器人坐标转换方法

这是离线编程中最常见的痛点。标准流程：
1. 从 CAD 中提取目标点的 XYZ 坐标（在 CAD 自身的坐标系下）
2. 在机器人上定义与 CAD 原点对应的 BASE 坐标系（3 点法）
3. 计算平移偏移量：`P_robot = P_cad - BASE_origin`
4. 转换旋转顺序：CAD 一般用 ZYX 欧拉角，KUKA 用 ZYX（A=Z, B=Y, C=X）
5. 使用 RoboDK 的自动坐标对齐功能可简化此过程

## 适用场景

- **Agent2 知识生成**：生成 KUKA 搬运/焊接程序模板
- **RAG 检索**：匹配"KUKA BASE 怎么标定""PTP LIN CIRC 区别""E6POS S T 参数""OrangeEdit 怎么用""KUKA 坐标系"等查询
- **故障排查**：奇异点、S/T 参数错误导致的位姿异常诊断

<!-- self_check: K2_20260804 ✓ ①②③④⑤⑥⑦ -->
