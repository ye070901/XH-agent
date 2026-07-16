# 人1：配置 + LLM层 + BaseAgent + 启动脚本

## 你要做什么

三个模块都是基础设施，其他人靠你才能开工。

### 1. config.py — 读 .env 配置

提供 `settings` 对象，其他人 `from config import settings` 拿配置。

```python
settings.LLM_PROVIDER    # "deepseek"
settings.LLM_API_KEY     # "sk-xxx" 或 ""
settings.LLM_MODEL       # "deepseek-chat"
```

### 2. LLM 层 — 统一调用入口

文件：`llm/client.py`

- `await llm.call(system_prompt, user_message)` 调大模型，返回文本
- `await llm.call_json(system_prompt, user_message)` 调大模型，返回 dict
- **没有 API Key 时自动返回模拟数据**。看 system_prompt 判断该返回诊断还是资源。模拟数据从 user_message 里提取信息，跟着输入变

### 3. BaseAgent — Agent 基类

文件：`agents/base.py`

封装 `call_llm()` 和 `call_llm_json()`，人2、人3、人4 继承它写自己的 Agent。

### 4. .env.example + start.bat

- `.env.example`：模板文件，每个配置项有注释
- `start.bat`：双击检查 .env → pip install → 启动后端（新窗口）→ 启动前端（新窗口）

## 你怎么测

- 不配 Key → 调 `call_json("学情诊断", "学习目标: Python")` → 不返回空
- 配 Key → 同样调用 → 返回真实 LLM 内容
- BaseAgent 被人2/3/4 继承后 `call_llm_json()` 不报错
- 双击 start.bat → 后端和前端都启动
