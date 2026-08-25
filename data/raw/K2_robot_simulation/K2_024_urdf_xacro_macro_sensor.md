# URDF Xacro 宏与传感器插件建模

- **来源**：http://wiki.ros.org/urdf/Tutorials
- **作者/机构**：Open Robotics / ROS 社区
- **日期**：2023-08-22
- **权威等级**：A
- **领域标签**：K2_ROS仿真
- **摘要**：Xacro 是 URDF 的宏语言，可消除重复建模、支持参数化与模块化。本文讲解 Xacro 宏定义、参数传递、文件包含、惯性/视觉/碰撞属性规范，以及如何在 Xacro 中挂载传感器插件，帮助高效搭建可复用的机器人模型用于 Gazebo 与 MoveIt。

---

## 正文

直接手写 URDF 存在大量重复（左右对称的关节、多段连杆等），且修改困难。Xacro 通过**宏（Macro）与参数（Property）**把模型模块化、参数化，是 ROS 机器人建模的主流方式。

### 一、宏定义与调用

```xml
<xacro:macro name="wheel" params="name prefix">
  <link name="${prefix}_${name}">
    <visual>
      <geometry><cylinder radius="0.05" length="0.04"/></geometry>
      <material name="black"/>
    </visual>
    <inertial>
      <mass value="0.5"/>
      <inertia ixx="0.001" iyy="0.001" izz="0.001" ixy="0" ixz="0" iyz="0"/>
    </inertial>
  </link>
</xacro:macro>

<!-- 调用宏生成两个轮子 -->
<xacro:wheel name="left" prefix="base"/>
<xacro:wheel name="right" prefix="base"/>
```

### 二、参数与数学表达式

```xml
<xacro:property name="base_width" value="0.3"/>
<xacro:property name="pi" value="3.14159265"/>

<link name="base_link">
  <inertial>
    <mass value="${base_width * 2}"/>
  </inertial>
</link>
```

Xacro 支持 `${}` 表达式进行数值计算与字符串拼接。

### 三、文件包含（模块拆分）

```xml
<xacro:include filename="$(find my_robot)/urdf/materials.xacro"/>
<xacro:include filename="$(find my_robot)/urdf/sensors.xacro"/>
```

把底盘、机械臂、传感器拆成独立 `.xacro` 文件，主文件用 `include` 组装。

### 四、在 Xacro 中挂载传感器插件

```xml
<xacro:macro name="camera" params="name parent">
  <joint name="${name}_joint" type="fixed">
    <parent link="${parent}"/>
    <child link="${name}_link"/>
    <origin xyz="0.1 0 0.05" rpy="0 0 0"/>
  </joint>
  <link name="${name}_link">
    <visual><geometry><box size="0.03 0.03 0.03"/></geometry></visual>
    <sensor type="camera" name="${name}">
      <plugin name="${name}_controller" filename="libgazebo_ros_camera.so"/>
    </sensor>
  </link>
</xacro:macro>

<xacro:camera name="front_cam" parent="base_link"/>
```

### 五、转换与查看

```bash
# Xacro 转 URDF
xacro model.xacro > model.urdf
# 校验模型
check_urdf model.urdf
# 在 RViz 中查看
ros2 launch urdf_tutorial display.launch.py model:=model.urdf
```

### 六、建模规范（避免仿真异常）

- 每个 `<link>` 必须有 `<inertial>`（质量与惯量），否则 Gazebo 物理异常。
- 视觉（visual）与碰撞（collision）几何可不同，碰撞体尽量简化以提高性能。
- 关节 `origin` 使用统一约定（如 URDF 的 xyz/rpy），避免坐标系错乱。

## 适用场景

本文用于 XH-agent 回答"如何用 Xacro 建模""URDF 传感器插件怎么写"等问题，是 K2 ROS 建模与仿真环境搭建的基础知识。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
