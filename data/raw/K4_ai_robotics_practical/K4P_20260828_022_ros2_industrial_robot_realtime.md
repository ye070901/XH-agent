# ROS 2 实时接口：AI 节点与工业机器人控制器的确定性边界

- 来源 URL：[NVIDIA Isaac Manipulator](https://developer.nvidia.com/blog/advancing-robot-learning-perception-and-manipulation-with-latest-nvidia-isaac-release/)；[NVIDIA Isaac Sim Core API](https://docs.isaacsim.omniverse.nvidia.com/latest/core_api_tutorials/index.html)
- 作者/机构：NVIDIA；本文由 XH-agent 基于官方资料二次整理
- 发布日期：2025 / 2026 页面；本文整理日期 2026-08-28
- 来源权威等级：B
- 内容性质：官方 ROS 2/Isaac 资料的技术化二次整理；topic 名称为逻辑示例
- 领域标签：K4P_TECH_ROS2
- 摘要：从节点、消息、QoS、时间戳、心跳和超时角度说明 AI 与工业机器人控制器的实时集成，防止把非确定性的模型推理直接接到运动执行。

---

## 正文

### 1. 节点分层

```text
camera_node -> perception_node -> transform_node -> planner_node
                                                -> robot_driver/controller
gripper_state <------------------------------- execution_monitor
安全 PLC ------------------------------------> driver enable gate
```

AI 节点可以延迟、重启或输出无效结果；工业机器人驱动和安全控制必须定义确定性的超时和降级行为。

### 2. 逻辑消息

```yaml
header: {stamp, frame_id, seq}
target: {id, pose, confidence, model_revision}
validity: {status, max_age_ms, recipe_id}
```

`frame_id`、`stamp`、`seq` 缺一不可。目标随输送带移动时，驱动层应根据时间戳/编码器位置判断结果是否仍有效。

### 3. QoS 与超时策略

传感器观测可使用“最新样本优先”；机器人动作请求则要避免重复消费。每个请求要有序号和确认：`REQUESTED -> ACCEPTED -> EXECUTING -> COMPLETE/FAILED`。心跳丢失、消息年龄超过预算或驱动状态未知时，禁止继续发送新的运动请求。

### 4. 伪代码

```text
on_detection(msg):
    if msg.header.frame_id != expected_frame: return reject(FRAME)
    if now - msg.header.stamp > max_age: return reject(STALE)
    if msg.validity.recipe_id != active_recipe: return reject(RECIPE)
    queue.replace_latest(msg)

control_loop():
    if not safety_gate or not driver_heartbeat: hold()
    elif queue.has_valid() and robot_state == READY:
        send_once(queue.pop(), request_seq)
```

### 5. 故障恢复

AI 节点重启不应导致机器人自动继续旧动作；驱动重连后要重新读取机器人状态、工具、工作对象和安全门状态。控制器拒绝轨迹、抓手反馈失败或 PLC 复位时，动作请求应进入故障保持，等待人员确认。

## 适用场景

ROS 2/Isaac AI 节点与工业机器人控制器、PLC、相机和抓手的实时集成。

## 参考资料

1. [NVIDIA Isaac Manipulator](https://developer.nvidia.com/blog/advancing-robot-learning-perception-and-manipulation-with-latest-nvidia-isaac-release/)。
2. [Isaac Sim Core API tutorials](https://docs.isaacsim.omniverse.com/latest/core_api_tutorials/index.html)。

<!-- self_check: K4P_20260828_022 ✓ ①②③④⑤⑥⑦ -->
