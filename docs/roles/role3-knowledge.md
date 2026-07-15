# CLAUDE.md — 角色3：前端开发（副）

## 你的任务（MVP 阶段）

和角色8 一起写前端——各负责一半。角色8 写左边（输入表单 + API 调用），你写右边（结果展示 + Markdown 渲染 + 错误处理）。

## MVP 要做什么

1. **写结果展示区（7/17-20）**
   - Tab 1 学情诊断：metric 卡片、知识盲区 expander、知识掌握度 progress bar
   - Tab 2 学习资源：资源 expander、Markdown 渲染
   - 代码写在 `frontend/streamlit/app.py`

2. **写错误处理 + 状态提示（7/21-22）**
   - 后端未连接时显示提示
   - 生成失败时友好报错
   - 首次打开时显示引导文字

3. **和角色8 联调（7/23-24）**
   - 角色8 写表单 + API 调用
   - 你写结果展示
   - 约定：角色8 把数据存到 `st.session_state.result`，你从里面读

**详细步骤见：** `docs/MVP_TASKS.md` — 角色3 部分

## 和角色8 的分工界线

```
角色8: 侧边栏 + 生成按钮 + API 调用 + st.session_state
角色3: 主区域两个 tab + Markdown 渲染 + 错误提示

互不踩对方的地盘。
同一个文件 app.py，用 Git 协调。
```

## Phase 2 你的角色会变

MVP 你做前端。Phase 2 会回到知识库方向（RAG 检索 + 向量库），但那是 8 月的事。
