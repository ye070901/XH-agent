# ABB MultiMove 多机器人协同编程

- **来源**：https://library.e.abb.com/public/5d7fe26f6f47445cb12d288e455e0c8f/3HAC050961%20AM%20MultiMove%20RW%206-en.pdf
- **作者/机构**：ABB Robotics（官方应用手册 3HAC050961）
- **日期**：2023-06
- **权威等级**：A
- **领域标签**：K2_协同编程
- **摘要**：依据 ABB 官方 MultiMove 应用手册，讲解单控制器多机器人/机械单元协同编程。涵盖 Independent 与 Coordinated 两种选项、独立/半协调/协调同步三种运动模式、SyncMoveOn/SyncMoveOff 同步指令、WaitSyncTask 任务同步、协调工作对象（moving workobject）编程。含双机器人协同搬运的完整 RAPID 示例与 RobotStudio MultiMove 站搭建步骤。

---

## 正文

### 一、MultiMove 概念

MultiMove 允许单个 IRC5/OmniCore 控制器同时控制多台机器人与机械单元（变位机、导轨等），节省控制器硬件成本，并支持机器人之间的协调运动。

| 选项 | 能力 |
|------|------|
| MultiMove Independent | 独立运动 + 半协调运动 |
| MultiMove Coordinated | 含 Independent 全部功能 + 协调同步运动 |

- 一个控制器最多带 4 个驱动模块（最多 4 台机器人），总轴数可达 36
- MultiMove 始终包含 Multitasking（多任务）；Coordinated 另含 Multiple Axis Positioner

### 二、三种运动模式

| 模式 | 说明 | 典型场景 |
|------|------|----------|
| 独立运动 | 各机器人独立执行程序，互不等待 | 独立上下料 |
| 半协调运动 | 机器人操作静止工件，变位机保持不动 | 变位机定位后焊接 |
| 协调同步运动 | 机器人与持工件的变位机/机器人同步运动 | 变位机边转边焊 |

### 三、同步指令

```rapid
SyncMoveOn;                        ! 进入同步运动模式
...                                ! 同步的 Move 指令
SyncMoveOff;                       ! 退出同步运动模式

WaitSyncTask id, task_list;        ! 等待指定任务到达同步点
SyncMoveUndo;                      ! 手动移动程序指针时撤销同步
```

### 四、协调工作对象（moving workobject）

协调运动时，焊接/加工指令的目标点基于一个「随变位机移动的工作对象」。在同步模式下，控制器实时计算移动工作对象上的点位：

```rapid
! 任务1（变位机）：旋转工件
SyncMoveOn;
MoveL pRotate, v100, fine, tool1;
SyncMoveOff;

! 任务2（焊接机器人）：在移动工件上焊接
SyncMoveOn;
ArcLStart pWeldStart, v50, seam1, weld1, fine, tGun \WObj:=wMovable;
ArcLEnd pWeldEnd, v50, seam1, weld1, fine, tGun \WObj:=wMovable;
SyncMoveOff;
```

### 五、双机器人协同搬运示例

场景：两台机器人同时夹持一根长梁，同步移动到装配位。

```rapid
! ===== TASK1（机器人 R1）=====
PROC main()
    MoveJ pHome1, v500, z50, tGrip1;
    WaitSyncTask 1, task_list;        ! 等 R2 到位
    SyncMoveOn;
    MoveL pPick1, v200, fine, tGrip1 \WObj:=wObj1;
    MoveL pPlace1, v200, fine, tGrip1 \WObj:=wObj1;
    SyncMoveOff;
ENDPROC

! ===== TASK2（机器人 R2）=====
PROC main()
    MoveJ pHome2, v500, z50, tGrip2;
    WaitSyncTask 1, task_list;
    SyncMoveOn;
    MoveL pPick2, v200, fine, tGrip2 \WObj:=wObj2;
    MoveL pPlace2, v200, fine, tGrip2 \WObj:=wObj2;
    SyncMoveOff;
ENDPROC
```

> 多任务 RAPID 中，每个任务的模块需在系统配置中分配对应 Motion Task；`task_list` 由控制器自动维护。

### 六、RobotStudio MultiMove 站搭建

1. 新建系统时选择 MultiMove 选项（Independent 或 Coordinated）
2. 在布局中导入多台机器人与变位机，关联到同一控制器
3. 用 MultiMove tool 把运动分配到各机器人（所有机器人须属同一系统）
4. 分别编写每个 Motion Task 的 RAPID 程序
5. 同步模式下运行仿真，验证协调轨迹与碰撞

## 适用场景

- **Agent2 知识生成**：多机器人协同、变位机协调焊接程序模板
- **RAG 检索**：匹配「MultiMove 怎么编程」「SyncMoveOn 用法」「协调运动」「多机器人协同」「变位机边转边焊」等查询
- **学情诊断**：判断用户对多任务、同步运动、moving workobject 的理解

<!-- self_check: K2_20260815 ✓ ①②③④⑤⑥⑦ -->
