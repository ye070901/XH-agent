# 人6：Streamlit 前端

## 你要做什么

文件：`frontend/streamlit/app.py` — 一个文件搞定全部。

## 输入

用户在页面上填的 9 个字段：

| 字段 | 控件 | 必填 |
|------|------|------|
| 学习目标 | `st.text_area` | ✅ |
| 学历 | `st.selectbox`（高中/大专/本科/硕士/博士） | ✅ |
| 专业 | `st.text_input` | ✅ |
| 技能 | `st.text_input` | ✅ |
| 工作年限 | `st.slider`（0-20） | ❌ |
| 行业 | `st.text_input` | ❌ |
| 岗位 | `st.text_input` | ❌ |
| 前置测试 | （暂放一个空数组） | ❌ |
| 资源类型 | `st.multiselect`（讲义/实操指南/测试题） | ✅ |

点"生成"按钮 → 调 POST /api/generate。

## 输出

三块展示在界面上：

**上面 → 学情诊断**
- `st.metric` ×3：学习风格、推荐难度、知识盲区数量
- `st.write`：整体总结
- `st.expander`：每个知识盲区展开（含优先级、原因）
- `st.progress`：每个知识点一条进度条

**中间 → 学习资源**
- `st.expander` + `st.markdown`：讲义、指南、测试题各一个展开块

**下面 → 审核意见**
- 每个资源后面跟着审核结果，有问题标红

## 开发时不依赖后端

```python
# 先从接口文档复制假数据用
FAKE_RESULT = {"diagnosis": {...}, "resources": [...], "audit": [...]}
result = FAKE_RESULT

# 联调时改成真调用
# response = requests.post("http://localhost:8000/api/generate", json=data, timeout=120)
# result = response.json()
```

## 你怎么测

- 所有表单控件能正常交互
- 点生成 → 诊断 tab 展示正常，进度条、展开块都没问题
- 资源 tab → Markdown 代码块有颜色、标题有变大
- 后端没启动 → 不白屏，有"请先启动后端"提示
- 换不同学习者 → 内容跟着变
