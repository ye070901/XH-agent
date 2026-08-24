# Gazebo 视觉传感器与点云仿真配置

- **来源**：https://classic.gazebosim.org/tutorials
- **作者/机构**：Open Robotics / Gazebo 社区
- **日期**：2023-09-18
- **权威等级**：A
- **领域标签**：K2_ROS仿真
- **摘要**：Gazebo 支持相机、激光雷达、RGB-D 深度相机等传感器仿真，是机器人视觉引导离线验证的基础。本文讲解在 URDF/SDF 中挂载传感器、配置 Gazebo 插件（camera、ray、depth_camera），以及发布图像与点云话题并在 RViz 中查看，帮助搭建带视觉的仿真环境。

---

## 正文

视觉引导（如 2D 定位、3D 点云抓取）是工业机器人离线仿真的重要环节。Gazebo 通过**传感器插件（Plugin）**在仿真中真实渲染并发布传感器数据，让视觉算法可以在上真机前离线跑通。

### 一、在 URDF 中挂载相机并配置插件

```xml
<link name="camera_link">
  <visual>...</visual>
  <sensor type="camera" name="camera1">
    <update_rate>30.0</update_rate>
    <camera>
      <horizontal_fov>1.047</horizontal_fov>
      <image>
        <width>640</width><height>480</height>
        <format>R8G8B8</format>
      </image>
      <clip><near>0.01</near><far>100</far></clip>
    </camera>
    <plugin name="camera_controller" filename="libgazebo_ros_camera.so">
      <ros>
        <namespace>robot</namespace>
        <remapping>image_raw:=image_raw</remapping>
      </ros>
      <camera_name>camera1</camera_name>
      <frame_name>camera_link</frame_name>
    </plugin>
  </sensor>
</link>
```

### 二、激光雷达（Lidar）与点云插件

```xml
<sensor type="ray" name="lidar">
  <ray>
    <scan>
      <horizontal>
        <samples>720</samples>
        <resolution>1</resolution>
        <min_angle>-1.57</min_angle>
        <max_angle>1.57</max_angle>
      </horizontal>
    </scan>
    <range><min>0.1</min><max>30</max><resolution>0.01</resolution></range>
  </ray>
  <plugin name="lidar_controller" filename="libgazebo_ros_ray_sensor.so">
    <ros>
      <namespace>robot</namespace>
    </ros>
    <output_type>sensor_msgs/PointCloud2</output_type>
    <frame_name>lidar_link</frame_name>
  </plugin>
</sensor>
```

### 三、RGB-D 深度相机（视觉引导常用）

使用 `libgazebo_ros_openni_kinect.so` 插件可同时发布彩色图与深度点云：

```xml
<plugin name="kinect" filename="libgazebo_ros_openni_kinect.so">
  <camera_name>camera</camera_name>
  <frame_name>camera_link</frame_name>
  <point_cloud>true</point_cloud>
</plugin>
```

### 四、话题与 RViz 查看

启动后可用命令查看数据流：

```bash
# 查看图像话题
ros2 run rqt_image_view rqt_image_view
# 查看点云话题列表
ros2 topic list | grep point
# RViz 添加 PointCloud2 与 Image 显示
ros2 run rviz2 rviz2
```

### 五、常见问题

- **无话题输出**：检查插件 `filename` 是否与 Gazebo 版本匹配（如 `libgazebo_ros_camera.so`）。
- **点云坐标漂移**：`frame_name` 需与 TF 树中的传感器坐标系一致。
- **黑屏/无图像**：相机朝向错误或被遮挡，调整 `<frame_name>` 位姿或 `min_angle`。

## 适用场景

本文用于 XH-agent 回答"Gazebo 里怎么加相机/雷达""如何仿真视觉引导"等问题，是 K2 视觉集成离线仿真的基础。

<!-- self_check: K2_20260824 ✓ ①②③④⑤⑥⑦ -->
