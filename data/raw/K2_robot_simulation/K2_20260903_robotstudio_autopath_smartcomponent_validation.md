# RobotStudio AutoPath、布局导入与 Smart Component 联调边界

- **来源**：[ABB RobotStudio](https://new.abb.com/products/robotics/robotstudio)、库内资料 [碰撞与可达性分析](K2_019_abb_robotstudio_collision_reachability.md)、[Smart Component](K2_017_abb_robotstudio_smart_component.md)
- **作者/机构**：ABB Robotics；本文由 XH-agent 整理
- **整理日期**：2026-09-03
- **权威等级**：A
- **领域标签**：K2_RobotStudio / K9_工艺仿真
- **摘要**：明确 AutoPath 是路径生成与验证辅助，不是安全认证；给出布局/CAD、机器人系统、Smart Component 信号和 RAPID 程序之间的联调顺序，并提示界面位置会随 RobotStudio 版本变化。

---

## 正文

### 1. 四类对象要分别验证

1. **布局/CAD**：导入的机器人、工装、围栏和工件模型应核对单位、原点、安装姿态、碰撞几何和版本。布局中“看见模型”不代表其 TCP、载荷、坐标或控制器配置正确。
2. **虚拟控制器与 RAPID**：创建的系统应与目标 RobotWare、机器人型号、选件和 I/O 配置匹配。RAPID 导入或同步后先执行语法/系统一致性检查。
3. **AutoPath/路径功能**：可辅助从曲线、边或曲面生成候选路径。生成结果仍要检查工具姿态、可达性、奇异性、碰撞、速度、转弯区和工艺质量。
4. **Smart Component**：用于模拟传感器、夹具、输送线和工件逻辑。组件信号必须与机器人/PLC 的普通 I/O 映射、初始状态和时序逐一对应。

### 2. 推荐联调顺序

```text
布局几何与坐标核对
  -> 创建/恢复匹配版本的虚拟控制器
  -> 配置 tooldata、wobjdata、负载和普通 I/O
  -> 单独验证 Smart Component 的初始状态与信号变化
  -> 生成/导入 RAPID 路径并检查
  -> 开启碰撞、可达性与时序验证
  -> 输出评审记录，真机低速复验
```

若 Smart Component 信号与 RAPID 的 `SetDO`/`WaitDI` 相连，必须验证两条路径：正常反馈和不反馈/超时。只验证“工件能动起来”会遗漏信号反相、初始状态错误和时序竞争。

### 3. 关于界面名称和“自动反向”

AutoPath、Layout、导入机器人和路径方向/反向等命令的菜单位置与可用选项取决于 RobotStudio、RobotWare、PowerPac 和授权版本。知识库不应把某个版本的按钮路径当作所有环境的固定事实。使用路径反向或自动生成 RAPID 后，仍须检查起终点、工具方向、工艺事件（如起弧/夹爪）、速度区和 I/O 时序，避免仅反转几何路径而遗漏程序语义。

### 4. 验收边界

仿真通过是现场验证的输入，不是安全或工艺验收的替代。真机必须在批准的安全条件、正确工具/坐标/负载和低速受控试运行后，才能进入自动生产。

<!-- self_check: K2_20260903 ✓ RobotStudio ✓ AutoPath ✓ SmartComponent ✓ version-boundary -->
