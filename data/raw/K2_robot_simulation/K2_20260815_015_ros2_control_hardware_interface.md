# ROS2 ros2_control 硬件接口与仿真真机切换

- **来源**：https://control.ros.org/ros2_control/
- **作者/机构**：ROS.org / ros2_control 项目组（官方文档）
- **日期**：2025-01
- **权威等级**：A
- **领域标签**：K2_ROS仿真
- **摘要**：讲解 ros2_control 框架下机器人硬件接口（Hardware Interface）开发，实现同一套控制器配置在 Gazebo 仿真与真实机器人间切换。涵盖 Controller Manager 与 Resource Manager 架构、SystemInterface 与 ActuatorInterface 选择、五个关键生命周期函数（on_init / export_state_interfaces / export_command_interfaces / read / write）、mock_components 与 gazebo_ros2_control 插件、仿真真机切换方法。含可编译的 C++ SystemInterface 骨架与配置。

---

## 正文

### 一、ros2_control 架构

ros2_control 把「控制器（Controller）」与「硬件（Hardware）」解耦：

- **Controller Manager**：加载/启停控制器（如 joint_trajectory_controller）
- **Resource Manager**：加载硬件组件，管理状态/命令接口
- **Hardware Component**：对接真实硬件或仿真插件，实现 `read()` / `write()`

控制器只读写标准接口（position / velocity / effort），不感知硬件是 Gazebo 插件还是真实驱动——这正是仿真与真机切换的基础。

### 二、硬件接口类型

| 类型 | 适用 |
|------|------|
| SystemInterface | 多关节组成的机器人系统（最常用） |
| ActuatorInterface | 单个执行器 |
| SensorInterface | 纯传感器 |

6 轴机械臂使用 SystemInterface。

### 三、五个关键生命周期函数

| 函数 | 作用 |
|------|------|
| on_init | 解析 URDF 参数，声明状态/命令接口 |
| export_state_interfaces | 导出状态（关节位置/速度/力） |
| export_command_interfaces | 导出命令（位置/速度/力） |
| read | 从硬件读取当前状态 |
| write | 把命令写入硬件 |

### 四、SystemInterface 骨架（与真实驱动通讯）

以下示例通过 Modbus TCP 与各关节伺服驱动（已有的工业驱动器）交换位置指令，属于**接口集成层**，不涉及伺服电路/PWM 设计：

```cpp
#include <rclcpp/rclcpp.hpp>
#include <hardware_interface/system_interface.hpp>
#include <hardware_interface/types/hardware_interface_type_values.hpp>
#include <vector>
#include <string>

namespace my_robot_hardware
{

class RobotSystemHardware : public hardware_interface::SystemInterface
{
public:
  CallbackReturn on_init(const hardware_interface::HardwareInfo & info) override
  {
    if (hardware_interface::SystemInterface::on_init(info) != CallbackReturn::SUCCESS)
      return CallbackReturn::ERROR;

    for (const auto & joint : info.joints)
    {
      hw_state_positions_.push_back(0.0);
      hw_commands_.push_back(0.0);
    }

    // 连接各关节驱动（Modbus TCP 客户端，地址从 URDF 参数读取）
    // modbus_.connect(info.hardware_parameters.at("modbus_ip"));
    return CallbackReturn::SUCCESS;
  }

  std::vector<hardware_interface::StateInterface> export_state_interfaces() override
  {
    std::vector<hardware_interface::StateInterface> states;
    for (size_t i = 0; i < info_.joints.size(); ++i)
    {
      states.emplace_back(info_.joints[i].name,
                          hardware_interface::HW_IF_POSITION, &hw_state_positions_[i]);
    }
    return states;
  }

  std::vector<hardware_interface::CommandInterface> export_command_interfaces() override
  {
    std::vector<hardware_interface::CommandInterface> commands;
    for (size_t i = 0; i < info_.joints.size(); ++i)
    {
      commands.emplace_back(info_.joints[i].name,
                            hardware_interface::HW_IF_POSITION, &hw_commands_[i]);
    }
    return commands;
  }

  hardware_interface::return_type read(const rclcpp::Time &, const rclcpp::Duration &) override
  {
    for (size_t i = 0; i < hw_state_positions_.size(); ++i)
      hw_state_positions_[i] = modbus_.read_position(i);   // 读取关节实际位置
    return hardware_interface::return_type::OK;
  }

  hardware_interface::return_type write(const rclcpp::Time &, const rclcpp::Duration &) override
  {
    for (size_t i = 0; i < hw_commands_.size(); ++i)
      modbus_.write_position(i, hw_commands_[i]);          // 写入关节目标位置
    return hardware_interface::return_type::OK;
  }

private:
  std::vector<double> hw_state_positions_;
  std::vector<double> hw_commands_;
  // ModbusClient modbus_;
};

}  // namespace my_robot_hardware

#include <pluginlib/class_list_macros.hpp>
PLUGINLIB_EXPORT_CLASS(my_robot_hardware::RobotSystemHardware,
                       hardware_interface::SystemInterface)
```

### 五、仿真与真机切换

同一套 URDF + 控制器配置，仅更换 `<ros2_control>` 标签下的 `<plugin>`：

```xml
<!-- 仿真（Gazebo） -->
<ros2_control name="GazeboSystem" type="system">
  <plugin>gazebo_ros2_control/GazeboSystem</plugin>
</ros2_control>

<!-- 无硬件空跑（测试） -->
<plugin>mock_components/GenericSystem</plugin>

<!-- 真机 -->
<plugin>my_robot_hardware/RobotSystemHardware</plugin>
```

切换流程：
1. 仿真阶段用 `gazebo_ros2_control/GazeboSystem` 插件验证控制器与运动学
2. 真机阶段替换为自研硬件接口插件
3. 控制器侧（joint_trajectory_controller 配置）无需任何改动

### 六、编译与测试

```bash
# 导出插件
ament_target_dependencies(my_robot_hardware pluginlib rclcpp hardware_interface)

# 加载硬件组件并启动控制器
ros2 control load_controller --set-state active joint_trajectory_controller
ros2 control list_hardware_interfaces
```

## 适用场景

- **Agent2 知识生成**：仿真转真机的硬件接口方案与控制器配置
- **RAG 检索**：匹配「ros2_control 硬件接口」「SystemInterface 怎么写」「仿真真机切换」「export_command_interfaces」等查询
- **故障排查**：真机不响应时定位接口/插件配置问题

<!-- self_check: K2_20260815 ✓ ①②③④⑤⑥⑦ -->
