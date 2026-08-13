# ABB Palletizing 码垛工艺包 — 官方模板与 PowerPac 完整指南

- **来源**：https://www.abb.com/global/en/areas/robotics/products/software/application-templates/palletizing-template
- **作者/机构**：ABB Robotics（官方）
- **日期**：2025-01
- **权威等级**：A
- **领域标签**：K2_搬运工艺包
- **摘要**：ABB 官方 Palletizing Template 与 Palletizing PowerPac 完整技术方案。包含图形化码垛配方编辑器、预置 RAPID 模块（PmMain/PmUtility/PmProjMgr/PmProjServer）、码垛模式设计器（行列层三维布局）、4 点示教快速部署法（仅需示教 Target_start/row/column/layer 四点即可自动计算全部码垛位姿）、Offs() 函数矩阵变换实现多层多列循环、奇异点自动规避与 Multi-Pick 多抓取集成。官方手册 394 页。

---

## 正文

### 一、ABB 码垛软件产品线

| 产品 | 适用对象 | 特点 |
|------|----------|------|
| **Palletizing PowerPac** | IRC5/OmniCore 工业机器人 | 功能完整，支持复杂多层混合码垛、输送链跟踪 |
| **Palletizing Template** | GoFa/SWIFTI 协作机器人 | 免费模板、图形化配方编辑、Web FlexPendant 界面 |

PowerPac 替代了早期的 PickMaster 5，是 ABB 码垛应用的核心工艺包。Template 是免费的协作用版本，部署速度比传统方式快 80%。

### 二、4 点示教快速部署法

这是 ABB 码垛最核心的编程方法——仅需示教 4 个基准点即可自动计算所有码垛位姿：

| 示教点 | 位置 | 说明 |
|--------|------|------|
| **Target_start** | 托盘第一个放置位置 | 最靠近机器人的底层角点 |
| **Target_row** | 行方向最远点 | 同一层、同一列，沿行方向最远位置 |
| **Target_column** | 列方向最远点 | 同一层、同一行，沿列方向最远位置 |
| **Target_layer** | 最高层对应点 | 最顶层的 Target_start 正上方位置 |

**操作步骤**：

1. **确认工具定义**：设置吸盘/夹具的 TCP（通常位于工具底面中心，Z 轴垂直向下）
2. **设定码垛参数**：
   ```
   行方向数量：5
   列方向数量：4
   层数：3
   行间距：自动计算 = (Target_row - Target_start) / (行数-1)
   列间距：自动计算 = (Target_column - Target_start) / (列数-1)
   层间距：自动计算 = (Target_layer - Target_start) / (层数-1)
   ```
3. **示教 4 个基准点**：
   - 手动操控机器人至 Target_start → 记录位置
   - 手动操控机器人至 Target_row → 记录位置
   - 手动操控机器人至 Target_column → 记录位置
   - 手动操控机器人至 Target_layer → 记录位置
4. **定义取料位置**：示教产品来料位置的抓取点
5. **设置接近高度**：抓取前/放置前的安全高度偏移（如 Z+200mm）
6. **完成设置 → 自动生成全部程序**

**核心优势**：码垛方向不需要与机器人世界坐标 X/Y 平行——系统自动根据示教的四点计算任意方向的码垛坐标系。

### 三、RAPID Offs() 码垛循环实现

若不用 PowerPac，可手写 RAPID 实现码垛逻辑：

```rapid
MODULE Palletizer
    PERS tooldata tGripper := [TRUE, [[0,0,120],[1,0,0,0]], [2,[0,0,80],[1,0,0,0],0,0,0]];
    PERS wobjdata wPallet := [FALSE,TRUE,"",[[1000,200,0],[1,0,0,0]],[[0,0,0],[1,0,0,0]]];

    CONST num ROWS := 5;       ! 每层行数
    CONST num COLS := 4;       ! 每层列数
    CONST num LAYERS := 3;     ! 层数
    CONST num ROW_SPACE := 120;
    CONST num COL_SPACE := 100;
    CONST num LAYER_HEIGHT := 150;

    CONST robtarget pOrigin := [[1000,200,50],[0.707,0,0.707,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];

    PROC main()
        VAR num row, col, layer;

        FOR layer FROM 0 TO LAYERS-1 DO
            FOR col FROM 0 TO COLS-1 DO
                ! 偶数层从行0开始，奇数层从行ROWS-1开始（交错堆叠增强稳定性）
                IF (layer MOD 2) = 0 THEN
                    FOR row FROM 0 TO ROWS-1 DO
                        Place(row, col, layer);
                    ENDFOR
                ELSE
                    FOR row FROM ROWS-1 TO 0 STEP -1 DO
                        Place(row, col, layer);
                    ENDFOR
                ENDIF
            ENDFOR
        ENDFOR
    ENDPROC

    PROC Place(num row, num col, num layer)
        VAR robtarget target;
        target := Offs(pOrigin, row*ROW_SPACE, col*COL_SPACE, layer*LAYER_HEIGHT);
        MoveJ Offs(target, 0, 0, 200), v500, z10, tGripper \WObj:=wPallet;
        MoveL target, v100, fine, tGripper \WObj:=wPallet;
        SetDO DO_Gripper, 0;
        WaitTime 0.2;
        MoveL Offs(target, 0, 0, 200), v200, z10, tGripper \WObj:=wPallet;
    ENDPROC
ENDMODULE
```

### 四、PowerPac 项目配置步骤

#### 4.1 工作站搭建（在 RobotStudio 中）
1. 安装 Palletizing PowerPac 插件
2. 导入机器人和末端工具（吸盘、夹爪或叉式）
3. 导入进料输送带和出料托盘模型
4. 添加 Smart 组件——输送带动画、传感器检测

#### 4.2 产品数据定义
```
产品类型：Box
尺寸：400×300×200 mm
重量：15 kg
朝向：长边沿 X 轴
最大吸取加速度：5 m/s²
```

#### 4.3 码垛模式创建
1. Pattern Designer → 新建模式 "Pattern_5x4"
2. 设置行数 5、列数 4
3. 可视布局网格自动生成 20 个放置位置
4. 启用层间交错（interlocking）增强稳定性
5. 预览 3D 码垛效果

#### 4.4 Job 向导配置
1. 选择托盘 → 绑定 Pattern_5x4
2. 选择进料输送带 → 定义取料位置
3. 设置层间垫纸（Slip Sheet）自动放置（如有需要）
4. 生成完整的 Pick-Place 程序序列

### 五、PowerPac 内置 RAPID 函数

| 函数 | 用途 |
|------|------|
| `PmStartProj` / `PmStopProj` | 启动/停止项目 |
| `PmStartFlow` / `PmStopFlow` | 控制物料流 |
| `PmGetTarget` / `PmAckTarget` | 获取并确认目标位置 |
| `PmCalcArmConf` | 计算关节配置（避开奇异点） |
| `PmCalcIntermid` | 计算中间过渡位置 |
| `PmGetFlowInfo` / `PmGetProjectInfo` | 运行时信息查询 |

### 六、Palletizing Template（协作版）快速上手

1. RobotStudio → Add-ins 标签 → 搜索 "Palletizing" → 安装
2. 加载预置 RAPID 模块（PmMain / PmUtility 等）
3. 在图形化配方编辑器中：
   - 定义产品（尺寸、重量、吸取方式）
   - 定义托盘（尺寸、最大层数）
   - 定义码垛模式（拖拽式布局）
4. 自动生成 RAPID 程序和 FlexPendant Web 界面
5. 部署后在 FlexPendant 上通过触摸屏直接选择配方、修改参数

## 适用场景

- **Agent2 知识生成**：码垛工作站程序模板生成
- **RAG 检索**：匹配"ABB 码垛工艺包怎么用""PowerPac 4 点法""Offs 码垛循环""层间交错怎么实现""吸盘码垛编程"等查询
- **学情诊断**：判断用户对工艺包的了解程度和 Offs() 函数掌握情况

<!-- self_check: K2_20260804 ✓ ①②③④⑤⑥⑦ -->
