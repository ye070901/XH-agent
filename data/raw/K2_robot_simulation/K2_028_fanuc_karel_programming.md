# FANUC KAREL 语言离线编程

- **来源**：https://damodev.csdn.net/6a43603910ee7a33f2849e04.html
- **作者/机构**：FANUC（KAREL 操作/参考手册 B-83144EN）
- **日期**：2023-06-30
- **权威等级**：A
- **领域标签**：K2_程序编写调试
- **摘要**：KAREL 是 FANUC 的类 Pascal 过程化编程语言，适合复杂逻辑、数据处理与 IO 通讯，弥补 TP 示教程序的不足。本文讲解 KAREL 程序结构、编译（.KL→.PC）、ROBOGUIDE 中创建与运行，以及 KAREL 与 TP 程序的互相调用，扩展离线编程能力。

---

## 正文

TP 程序擅长运动示教，但处理复杂逻辑（字符串、文件、循环、异常）能力有限。KAREL 作为 FANUC 的过程化语言，可编写结构化程序，与 TP 程序配合使用，是高级离线编程的核心技能。

### 一、程序结构

```karel
PROGRAM HELLO_WORLD

CONST
    GREETING = 'HELLO WORLD'

VAR
    cnt : INTEGER

BEGIN
    FOR cnt = 1 TO 3 DO
        WRITE(GREETING, CR)
    ENDFOR
END HELLO_WORLD
```

要点：
- `PROGRAM` 语句必须位于首行，`BEGIN...END` 之间是可执行代码。
- 声明区可包含 `CONST`、`TYPE`、`VAR`、`ROUTINE`。

### 二、常用数据类型与结构

| 类型 | 说明 |
|------|------|
| `INTEGER` / `REAL` | 整数 / 实数 |
| `STRING[n]` | 定长字符串 |
| `BOOLEAN` | 逻辑值 |
| `XYZWPR` | 位置数据（含姿态） |
| `JOINTPOS` | 关节位置 |

控制结构支持 `IF...THEN...ELSE...ENDIF`、`FOR...ENDFOR`、`WHILE...ENDWHILE`、`REPEAT...UNTIL`。

### 三、在 ROBOGUIDE 中创建与编译

1. 工作单元软件版本选 V7.30 以上，并勾选 **KAREL（R632）** 选项。
2. `Project → New File → KAREL Source (.kl)` 创建源文件，或用编辑器（如 OLPC PRO）编写后导入。
3. 编辑器内点击 **Build**，把 `.KL` 编译为 `.PC`（p-code），自动加载进虚拟控制器。
4. 在示教器面板用 **Shift + FWD** 运行程序。

### 四、KAREL 与 TP 互调

- **TP 调用 KAREL**：需系统变量 `KAREL_ENB$ = 1`，TP 中用 `CALL` 指令调用 KAREL 程序。
- **KAREL 调用 TP**：KAREL 中用 `RUN_TPE(...)` 或通过 `%ENVIRONMENT` 执行运动。

```karel
PROGRAM MOTION_TEST
%NOLOCKGROUP
BEGIN
    -- KAREL 中执行运动需借助 TP 或运动扩展
    WRITE('Start motion', CR)
END MOTION_TEST
```

### 五、真机部署

1. 将编译好的 `.PC` 文件拷贝到内存卡根目录。
2. 控制器 `File → Load` 加载到 FROM 或 RAM。
3. 在 SELECT 屏选中 KAREL 程序运行（KAREL 程序内容不可在 EDIT 屏查看）。

### 六、限制与注意

- ROBOGUIDE 中 **Socket Messaging** 通讯程序无法在仿真中运行，需真机测试。
- KAREL 运动控制能力有限，通常负责逻辑，运动仍用 TP 或组合使用。

## 适用场景

本文用于 XH-agent 回答"FANUC KAREL 怎么写""KAREL 和 TP 怎么配合"等问题，是 K2 程序编写调试主题的高级内容。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
