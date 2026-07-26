# 人员6 — Streamlit 前端可视化

## 角色定位

用户界面 + 演示效果。负责所有前端交互、数据可视化、Agent 协同过程呈现。评分标准 15 分的"用户体验"由你直接决定。

## 依赖关系

```
被谁依赖：全体 → 演示视频素材来自你的界面

依赖谁：人员5 → 全部 API 端点 + WebSocket
        人员1 → agent_log 事件格式（画拓扑图的原始数据）
```

## 技术栈

| 需求 | 方案 |
|------|------|
| 页面框架 | Streamlit（已有代码基础） |
| 知识雷达图 | ECharts radar（`st.components.v1.html` 嵌入） |
| Agent 拓扑图 | ECharts graph/force（力导向布局） |
| 辩论 timeline | 自定义 HTML/CSS（`st.components.v1.html`） |
| 学习路径 DAG | ECharts tree/sankey |
| 实时数据 | WebSocket（在 components.v1.html 的 script 中 `new WebSocket()`） |
| 指标面板 | `st.metric` 原生 |
| CSS 主题 | 自定义 CSS（已有暗色主题基础） |

## 第一阶段：7/27 — 8/1（6天）

### 任务 1.1：追问交互界面（2天）

API 返回`status: "need_clarification"`时表单区切换为追问模式。3个selectbox追问（方向/基础/目标）。用户填完→调`POST /api/clarify`→拿到refined_goal→重新调`POST /api/generate`。

### 任务 1.2：知识雷达图组件（2天）

**文件**：`frontend/streamlit/components/radar_chart.py`（新建）

ECharts radar图嵌入。每个topic一条轴，level值决定位置，confidence<0.3的虚线标记。

### 任务 1.3：资源展示区优化（2天）

三种资源类型用tabs切换(lecture/guide/quiz)。每条技术断言后的`[来源: ...]`渲染为可折叠溯源面板。审核意见跟对应资源展示在一起。

**交付物**：追问面板 + 雷达图组件 + 升级版资源展示

## 第二阶段：8/3 — 8/10（8天）

### 任务 2.1：Agent 协同拓扑图（3天）

**文件**：`frontend/streamlit/components/agent_topology.py`（新建）

ECharts力导向图。WebSocket实时更新节点颜色：thinking→黄色闪烁 / acting→绿色脉冲 / done→蓝色静态 / error→红色。

### 任务 2.2：辩论过程可视化（3天）

**文件**：`frontend/streamlit/components/debate_timeline.py`（新建）

垂直timeline展示每轮辩论：🔴Agent3质询 → 🟢Agent2/4应诉(concede/rebut/accept_challenge) → ⚪裁决。原文引用可折叠展开。

### 任务 2.3：学习路径 DAG 图（1.5天）

**文件**：`frontend/streamlit/components/learning_path_dag.py`（新建）

基于skill_gaps依赖关系的DAG图，ECharts graph/tree布局，节点颜色表示掌握度。

### 任务 2.4：三项指标展示面板（0.5天）

**文件**：`frontend/streamlit/components/metrics_dashboard.py`（新建）

3个st.metric（幻觉率/适配率/覆盖率）+ 进度条 + 达标/不达标标记。

## 第三阶段：8/10 — 8/19

- 8/10-8/13：与人员5联调API + WebSocket连通性 + 闸门1追问交互完整流程
- 8/14-8/17：UI打磨（加载骨架屏/气球反馈/演示模式Mock数据开关/全局CSS最后一轮）
- 8/18-8/19：演示视频素材准备（3组学习者输入/关键步骤截图）

## 验收标准

- [ ] 追问交互：输入"我想学AI"→显示3个追问→填完后重新生成
- [ ] 知识雷达图：5个以上知识点清晰可见
- [ ] Agent 拓扑图：实时看到Agent状态流转
- [ ] 辩论 timeline：每轮质询/应诉/裁决清晰区分
- [ ] 学习路径 DAG：5个以上节点依赖关系清晰
- [ ] 三项指标：3个metric数字正确展示
- [ ] 演示模式开关：一键切换Mock数据
- [ ] 后端挂了不白屏，有明确错误提示
- [ ] WebSocket断开时显示"重连中"
