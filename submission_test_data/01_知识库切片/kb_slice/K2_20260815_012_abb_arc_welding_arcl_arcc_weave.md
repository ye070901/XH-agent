# ABB 弧焊指令 ArcL/ArcC 与摆焊编程

- **来源**：https://tech-community.robotics.abb.com/t/how-to-activate-weaving-arcwelding-powerpac/3410
- **作者/机构**：ABB Robotics（官方技术社区 + RAPID 弧焊参考手册）
- **日期**：2024-11
- **权威等级**：B
- **领域标签**：K2_焊接工艺包
- **摘要**：深入讲解 ABB 弧焊指令结构与数据定义。涵盖 seamdata（起弧预气/收弧回烧时序）与 welddata（焊接电压/电流/送丝速度/行进速度）、weavedata 摆焊参数（weave_shape 形状 0~3、weave_type 轴参与方式、宽度/长度/高度）、ArcLStart/ArcL/ArcLEnd 与 ArcCStart/ArcC/ArcCEnd 六类指令的完整语法与组合规则。含带摆焊的多层多道焊 RAPID 示例与 RobotStudio Arc Welding PowerPac 摆焊激活步骤。

---

## 正文

### 一、弧焊指令体系

ABB 弧焊程序必须遵循「起弧 → 焊接 → 收弧」结构：

- `ArcLStart` / `ArcCStart` —— 起弧（直线/圆弧起点）
- `ArcL` / `ArcC` —— 中间焊接点（直线/圆弧）
- `ArcLEnd` / `ArcCEnd` —— 收弧（直线/圆弧终点）

每个弧焊程序必须成对使用 Start 与 End；中间焊接点用不带 Start/End 的指令。

### 二、seamdata 与 welddata

`seamdata` 定义起弧/收弧阶段（送气、回烧等时序），`welddata` 定义焊接阶段的工艺参数：

| 数据 | 关键字段 | 含义 |
|------|----------|------|
| seamdata | purge_time | 焊前气体吹扫时间 |
| seamdata | preflow_time | 保护气预通气时间 |
| seamdata | back_time | 收弧回烧时间 |
| seamdata | postflow_time | 保护气滞后关闭时间 |
| welddata | weld_speed | 焊接行进速度 mm/s |
| welddata | weld_voltage | 焊接电压 V |
| welddata | weld_wirefeed | 送丝速度 m/min |

### 三、weavedata 摆焊参数

`weavedata` 定义摆焊（横向摆动）运动：

| 参数 | 取值 | 说明 |
|------|------|------|
| weave_shape | 0 | 无摆焊 |
| weave_shape | 1 | 平面锯齿摆焊 |
| weave_shape | 2 | 空间 V 形摆焊 |
| weave_shape | 3 | 空间三角摆焊 |
| weave_type | 0 | 全轴参与摆焊 |
| weave_type | 1 | 仅腕轴参与摆焊 |
| weave_length | mm | 一个摆焊周期长度 |
| weave_width | mm | 摆焊宽度（焊道宽度） |
| weave_height | mm | 空间摆焊高度 |

### 四、完整多层多道焊示例

```rapid
MODULE ArcWeld
    PERS tooldata tGun := [TRUE, [[0,0,150],[1,0,0,0]], [2,[0,0,80],[1,0,0,0],0,0,0]];
    PERS wobjdata wWeld := [FALSE,TRUE,"",[[600,0,300],[1,0,0,0]],[[0,0,0],[1,0,0,0]]];

    PERS seamdata seam1 := [0.3, 0.5, 0.1, 0.5, 0, 0, 0, 0, 0, 0];
    PERS welddata weld1 := [220, 24, 8, 5, 0, 0, 0, 0, 0, 0];
    PERS weavedata wv1 := [1, 0, 5, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0];

    CONST robtarget pStart := [[600,0,302],[1,0,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];
    CONST robtarget pMid   := [[600,150,302],[1,0,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];
    CONST robtarget pEnd   := [[600,300,302],[1,0,0,0],[0,0,0,0],[9E9,9E9,9E9,9E9,9E9,9E9]];

    PROC main()
        WeldSeam;
    ENDPROC

    PROC WeldSeam()
        ! 接近点
        MoveJ Offs(pStart,0,0,80), v500, z10, tGun \WObj:=wWeld;
        ! 起弧 → 焊接（带摆焊）→ 收弧
        ArcLStart pStart, v100, seam1, weld1 \Weave:=wv1, fine, tGun \WObj:=wWeld;
        ArcL pMid, v100, seam1, weld1 \Weave:=wv1, z10, tGun \WObj:=wWeld;
        ArcLEnd pEnd, v100, seam1, weld1 \Weave:=wv1, fine, tGun \WObj:=wWeld;
        ! 退离
        MoveL Offs(pEnd,0,0,80), v200, z10, tGun \WObj:=wWeld;
    ENDPROC
ENDMODULE
```

> 注意：seamdata/welddata/weavedata 的字段数量随 RobotWare 版本不同，示例数组按常见版本给出，实际应以示教器上自动生成的数据结构为准。

### 五、Arc Welding PowerPac 摆焊激活

1. RobotStudio → Arc Welding PowerPac → 工艺模板（Process Template）中激活 weave data
2. 创建焊缝路径时选用该工艺模板，运动自动带摆焊
3. 修改摆焊：Modify Instructions → Weave → Modify Weave Data
4. 若摆焊未仿真：检查示教器 ArcWare 是否锁定摆焊，切到手动模式解除

## 适用场景

- **Agent2 知识生成**：弧焊程序模板、摆焊参数推荐
- **RAG 检索**：匹配「ArcL ArcC 区别」「seamdata welddata 怎么设」「摆焊参数」「多层多道焊程序」等查询
- **Agent3 初审**：校验弧焊程序是否缺 Start/End、摆焊参数是否合理

<!-- self_check: K2_20260815 ✓ ①②③④⑤⑥⑦ -->
