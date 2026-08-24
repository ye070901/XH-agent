# Universal Robots URSim 离线仿真与 PolyScope 编程

- **来源**：https://www.universal-robots.com/download/
- **作者/机构**：Universal Robots A/S
- **日期**：2024-02-20
- **权威等级**：A
- **领域标签**：K2_离线仿真
- **摘要**：URSim 是 Universal Robots 官方的离线仿真器，完整模拟 PolyScope 图形界面与控制器，程序编好后可直接移植到真机。本文讲解 URSim 安装（Docker/虚拟机）、PolyScope 编程、URScript 脚本语言，以及仿真程序移植到真机时的硬件注意事项。

---

## 正文

URSim 让工程师在电脑上完整复现 Universal Robots 的 PolyScope 编程环境与控制器行为，编写的程序可**几乎零修改**地部署到真实 UR 机器人，是协作机器人离线编程的首选工具。

### 一、安装方式（推荐 Docker）

```bash
# 拉取并运行 e-Series 的 URSim 镜像
docker run --rm -it -p 5900:5900 -p 6080:6080 \
  --name ursim universalrobots/ursim_e-series
```

- 浏览器访问 `http://localhost:6080/vnc.html` 打开 PolyScope 界面。
- 其它版本镜像：`universalrobots/ursim_polyscopex`（PolyScope X）、`universalrobots/ursim_cb3`（CB3 系列）。
- 也可下载 Linux 安装包或使用官方虚拟机镜像（VDI）在 Windows 上运行。

### 二、PolyScope 图形化编程

1. 在 Program 树中用「Move」「Waypoint」「Set」「Wait」「Popup」等节点搭建流程。
2. 示教移动：拖动机械臂，用「Teach」记录当前位置为 Waypoint。
3. 设置 TCP、工具质量、重心与安全参数（Installation 菜单）。
4. 用「Play」运行并逐步验证逻辑。

### 三、URScript 脚本编程

PolyScope 节点底层对应 URScript，复杂逻辑可直接写脚本：

```urscript
def my_program():
  # 关节运动到安全位（q 为 6 关节角）
  movej([0.0, -1.57, 1.57, 0.0, 1.57, 0.0], a=1.2, v=0.5)
  # 直线运动到目标位（p 为 6 维位姿）
  movel(p[0.2, 0.3, 0.4, 0.0, 3.14159, 0.0], a=1.0, v=0.2)
  # 设置数字输出
  set_standard_digital_out(0, True)
  # 等待输入
  while get_standard_digital_in(1) == False:
    sleep(0.1)
  end
end
```

### 四、程序移植到真机

1. 在 URSim 中把程序保存为 `.urp` 文件，拷贝到 U 盘。
2. 插入真机控制箱，在 PolyScope 中 Load 加载。
3. 真机需补充**安全配置**（密码保护）、安全 IO 接线与急停输入。
4. 建议用 `sim_mode` 标志隔离仿真专用逻辑：

```urscript
sim_mode = True  # 部署到真机时改为 False
if not sim_mode:
  # 硬件相关调用（PLC 心跳、外部传感器）
  check_hardware()
end
```

### 五、URSim 的已知限制

| 限制 | 说明 |
|------|------|
| 急停不可用 | 无法仿真急停回路 |
| IO 状态不可设 | 标准数字 IO 部分仿真，Modbus 无真实通讯 |
| 无碰撞检测 | 自碰撞与周边碰撞不生效 |
| 力控无效 | Force mode 被接受但机器人不动 |

### 六、常见问题

| 现象 | 原因 | 对策 |
|------|------|------|
| 浏览器打不开 | 端口未映射 | 检查 `-p 6080:6080` |
| 真机轨迹不一致 | TCP/负载未对齐 | 真机补配 TCP 与质量 |
| 移植后 IO 异常 | 仿真 IO 与真机不符 | 用 `sim_mode` 隔离 |

## 适用场景

本文用于 XH-agent 回答"UR 机器人怎么做离线仿真""URSim 怎么装""PolyScope 和 URScript 区别"等问题，是 K2 协作机器人离线仿真的内容。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
