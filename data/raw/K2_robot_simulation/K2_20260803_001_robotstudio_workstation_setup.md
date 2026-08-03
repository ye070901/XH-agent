# ABB RobotStudio 离线仿真工作站搭建

- **来源**：https://new.abb.com/products/robotics/robotstudio
- **作者/机构**：ABB Robotics
- **日期**：2025-04-20
- **权威等级**：A
- **领域标签**：K2_离线仿真
- **摘要**：介绍使用 ABB RobotStudio 搭建离线仿真工作站的完整流程，包括机器人模型导入、工具创建、路径生成与碰撞检测，附带程序导出到真机的步骤。

---

## 正文

### 1. RobotStudio 简介

RobotStudio 是 ABB 官方的离线编程与仿真软件，支持在不占用实际机器人时间的情况下完成编程、调试和优化。主要功能包括：

- 3D 工作站建模与布局
- 机器人路径规划与仿真运行
- 碰撞检测与节拍分析
- 程序导出到真实机器人控制器

### 2. 工作站搭建步骤

**Step 1: 新建工作站**

1. 打开 RobotStudio → 文件 → 新建 → 空工作站
2. 设置项目名称和保存路径

**Step 2: 导入机器人模型**

1. 点击 "Home" → "Robot System" → "From Layout"
2. 在模型库中选择对应型号（如 IRB 1200、IRB 6700）
3. 拖入工作区，自动生成机器人系统

**Step 3: 导入夹具/工具**

```
1. 点击 "Import Library" → "Tool"
2. 选择夹具模型（或导入自定义 CAD 模型）
3. 将工具拖放到机器人的 tool0 坐标系上
4. 右键 → "Set as Tool" → 设置 TCP（工具中心点）参数
```

**Step 4: 创建工件坐标系**

```
1. "Other" → "Create Workobject"
2. 在工件上选择 3 个点定义坐标原点、X 轴方向、Y 轴方向
3. 命名工作对象（如 wobj_pallet）
```

### 3. 路径生成与仿真

**创建搬运路径示例：**

```
// RAPID 程序示例：简单搬运
MODULE PickAndPlace
    
    CONST robtarget pPick:=[[500, 300, 100],[1,0,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];
    CONST robtarget pPlace:=[[800, 500, 100],[1,0,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];
    
    PROC main()
        MoveJ pPick, v1000, z50, tool0;
        MoveL Offs(pPick,0,0,-50), v500, fine, tool0;
        Set doGrip;
        WaitTime 0.5;
        MoveL pPick, v500, z50, tool0;
        MoveJ pPlace, v1000, z50, tool0;
        MoveL Offs(pPlace,0,0,-50), v500, fine, tool0;
        Reset doGrip;
        WaitTime 0.5;
        MoveL pPlace, v500, z50, tool0;
    ENDPROC
ENDMODULE
```

### 4. 碰撞检测

在仿真运行前必须进行碰撞检测：

1. "Simulation" → "Collision Detection" → "Enable"
2. 设置碰撞对象（机器人本体 vs 周围设备）
3. 运行仿真，红色高亮表示发生碰撞
4. 调整路径或布局后重新验证

### 5. 程序导出到真机

1. "Controller" → "Transfer" → "Load Program"
2. 选择目标控制器（需建立 PC-控制器通信）
3. 确认程序参数后开始传输
4. 真机上首次运行使用低速+单步模式验证

## 适用场景

本文知识可用于 XH-agent 系统的仿真操作指导、程序编写辅助、离线编程教学场景。
