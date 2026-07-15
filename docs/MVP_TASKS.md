# MVP 个人任务清单

> 每人一份，照着做就行。看不懂的步骤把那段贴给 AI 问。

---

## 👤 角色1 — 后端核心（主）

**负责文件：** `backend/src/graph/orchestrator.py` + `backend/src/api/main.py` + `start.bat`

### 任务 1.1: 简化编排器（预计 20 分钟）

**目标：** 砍掉知识库检索、Agent 3 审核、辩论——只保留 Agent 1→Agent 2 两步。

**文件：** `backend/src/graph/orchestrator.py`

**具体步骤：**
1. 打开文件，找到 `run()` 方法（约第 42 行）
2. 删掉 `state` 字典里的这些字段：`"retrieved_chunks"`、`"audit_reports"`、`"debate_records"`、`"final_resources"`、`"rejected_resources"`、`"audit_reports"` 这些
3. `state["retrieved_chunks"]` 改为空列表 `[]`（Agent 2 不需要 KB 了）
4. 删掉 Step 2（知识检索）那一段代码
5. 删掉 Step 3 后面所有和审核/辩论/最终化相关的代码
6. Agent log 保留 diagnose 和 generation 两条
7. 删掉文件顶部 `from ..knowledge.store import knowledge_base` 这行

**验收：**
```bash
cd backend
python -c "from src.graph.orchestrator import workflow_engine; print('OK')"
# 不报错就过了
```

---

### 任务 1.2: 简化 API（预计 30 分钟）

**目标：** `/api/generate` 只做一件事：收 JSON → 调工作流 → 返回结果。

**文件：** `backend/src/api/main.py`

**具体步骤：**
1. 删掉 `from ..knowledge.store import knowledge_base`
2. 删掉 `from ..schemas import (...)` 除了用到的保留（目前只用 `settings`）
3. 删掉 `/api/knowledge` 和 `/api/knowledge/upload` 路由（没有 KB 了）
4. 确认 `/api/generate` 的请求格式是这样的：
   ```python
   {
       "education_level": "bachelor",   # high_school / junior_college / bachelor / master / phd
       "major": "计算机科学",
       "work_years": 1.0,               # 浮点数
       "industry": "互联网",
       "positions": ["Python开发"],      # 字符串数组
       "skills_used": ["Python", "Flask"],
       "pretest_results": [],            # 空数组也可以
       "learning_goal": "学习LangGraph构建AI Agent",
       "resource_types": ["lecture", "guide", "quiz"]  # 三选一/二/三都可以
   }
   ```
5. 返回格式：
   ```python
   {
       "task_id": "uuid",
       "status": "completed",
       "diagnosis": {...},       # Agent 1 的诊断结果
       "resources": [...],       # Agent 2 生成的资源列表
       "agent_log": [...]        # 每个步骤的日志
   }
   ```
6. 加 try/except：工作流报错时返回 500 + 错误信息，不要直接崩

**验收：**
```bash
# 启动后端
cd backend
python -m uvicorn src.api.main:app --port 8000

# 另一个终端
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"learning_goal":"学Python","resource_types":["lecture"]}'
# 返回 JSON，不是报错
```

---

### 任务 1.3: 写启动脚本（预计 15 分钟）

**目标：** 队友双击 `start.bat` 就能启动整个系统。

**文件：** `start.bat`（仓库根目录已有参考代码）

**具体步骤：**
1. 检查和修改现有的 `start.bat`
2. 确认 `.env` 不存在时自动从 `.env.example` 复制
3. 自动 `pip install` 依赖
4. 启动后端（新命令行窗口）
5. 等 3 秒
6. 启动 Streamlit 前端（新命令行窗口）
7. 打印两条链接
8. 加 `pause` 让窗口不自动关闭

**验收：** 双击 → 弹出两个新窗口 → 其中一个显示 `Uvicorn running on http://0.0.0.0:8000` → 另一个显示 Streamlit 地址

---

### 任务 1.4: 合并分支（7/28 做）

- 把所有人的分支 merge 到 dev
- 跑 `ruff check src/` + `python ../scripts/check_contracts.py`
- 打 tag `v0.1.0-mvp`
- merge dev → main

---

## 👤 角色2 — LLM 层（主）+ 后端测试（副）

**负责文件：** `backend/src/llm/client.py`

**辅助角色1：** 测试后端 API

### 任务 2.1: 加演示模式（预计 2-3 小时）

**目标：** 不配 API Key 的时候，系统也能跑——返回模拟的学情诊断和模拟的学习资源。

**文件：** `backend/src/llm/client.py`（仓库已有 `_demo_response` 方法参考）

**具体步骤：**

1. **看懂现有代码：**
   - 找到 `call_json()` 方法看怎么调用的
   - 找到 `_demo_response()` 方法看模拟数据怎么生成的
   - 仓库里 `_demo_response` 已经有诊断和资源两套模拟数据，你的工作是理解和完善

2. **完善诊断模拟数据：**
   - 找到 `_demo_response` 里 `if "学情诊断" in system_prompt` 那段
   - 目前是写死的学习者数据。你要让它**从 `user_message` 里提取信息**：
     - 用正则 `re.search(r'专业[：:]\s*(.+?)(?:\n|$)', user_message)` 提取专业
     - 用正则提取学习目标
     - 用正则提取学历
   - 让生成的模拟诊断结果里 `knowledge_map` 的 topic 和 learning_goal 相关
   - 不同学历 → `recommended_difficulty` 要跟着变（high_school→beginner, master→advanced）

3. **完善资源生成模拟数据：**
   - 找到 `if "知识专家" in system_prompt` 那段
   - 根据 `resource_type` 生成不同类型的模拟内容：
     - `lecture` → Markdown 讲义（含标题、小节、代码示例）
     - `guide` → 分步操作指南（含命令行）
     - `quiz` → 选择题+填空题（含正确答案）
   - 内容要和 `learning_goal` 匹配，不要总是"LangGraph 入门"

4. **兜底处理：**
   - system_prompt 识别不到类型 → 返回一个通用 JSON，不要返回空 `{}`
   - `call_json` 里如果 `_demo_response` 返回的不是 JSON → 用 `json.loads` 兜底

**验收：**
```python
# 不配 API Key 测三次
# 1. 诊断
from src.llm.client import llm
result = await llm.call_json("你是一个学情诊断专家", "学习目标：学Vue.js，专业：机械工程")
assert "skill_gaps" in result  # 有知识盲区
assert result["recommended_difficulty"] != ""

# 2. 生成讲义
result = await llm.call_json("你是一个知识专家和教育内容创作者", "生成类型：lecture")
assert result["title"] != ""

# 3. 生成实操指南
result = await llm.call_json("你是一个知识专家和教育内容创作者", "生成类型：guide")
assert "步骤" in result["content"] or "```bash" in result["content"]
```

---

### 任务 2.2: 测试角色1 的后端 API（预计 1-2 小时）

**具体步骤：**
1. 角色1 后端启动后，你第一个去测
2. 至少测 10 次不同的输入组合：
   - 不同学历（high_school / bachelor / master / phd）
   - 不同学习目标（学 Python / 学 LangGraph / 学深度学习）
   - 不同资源类型组合（只选 lecture / 选全部三种）
3. 记录每次返回的状态码和关键字段
4. 发现任何问题 → 截图 + 文字描述 → 发给角色1

**产出物：** 一个测试表格（Excel 或 Markdown），10 行，每行列出输入参数 + 返回状态 + 问题描述

---

## 👤 角色3 — 前端辅助 + 文档 + 演示

**辅助角色8：** 前端 UI 调整
**负责产出：** README 启动说明 + 演示分镜脚本

### 任务 3.1: 帮角色8 调前端（预计 3-4 小时，分散在 7/17-22）

**具体步骤：**
1. 先让角色8 把前端跑起来 → 你打开 http://localhost:8501
2. **检查 UI 文案：**
   - 每个输入框前面的标签是对的吗？
   - 中文是否通顺？
   - 学历下拉选项是否显示的是中文（不是 high_school 这种英文 key）
3. **检查展示效果：**
   - 诊断结果的"知识掌握度"进度条颜色合理吗？
   - 知识盲区展开后文字清晰吗？
   - Markdown 资源渲染正常吗？（代码块有没有高亮？）
4. **在不同条件下测：**
   - 浏览器窗口缩小到一半 → 布局不乱
   - 生成失败时（后端没启动）→ 前端不白屏，有提示文字
5. **记录问题：** 每发现一个 UI 问题 → 截图 → 发给角色8 → 修复后你再确认

---

### 任务 3.2: 写 README 启动说明（预计 2 小时）

**文件：** `README.md`

**要写清楚：**
1. **前提条件：** Python 3.10+ 怎么装？Git 怎么装？在哪里下载？
2. **克隆仓库：** `git clone ...` → `cd XH-agent`
3. **配置：** 复制 `.env.example` → `.env`，填 API Key（不填也能跑演示模式）
4. **启动方式 A：** 双击 `start.bat`（推荐）
5. **启动方式 B：** 手动启动（两个命令）
6. **打开浏览器：** http://localhost:8501
7. **怎么用：** 左边填信息 → 点生成 → 右边看结果
8. **常见问题：**
   - 端口被占用怎么办？
   - `pip install` 报错怎么办？
   - 前端白屏怎么办？

**参考格式：** 每一步都用一个 `###` 小标题 + 一段说明 + 代码块（如果需要输命令）+ 截图位置标注

---

### 任务 3.3: 写演示分镜脚本（预计 1.5 小时）

**目标：** 7/31 验收时，照着这个脚本演示系统。

**格式：**

| 时间 | 画面 | 操作 | 旁白 |
|------|------|------|------|
| 0:00 | 启动系统 | 双击 start.bat | "这是我们的领域知识个性化生成系统" |
| 0:30 | 前端页面 | 打开浏览器 | "左侧是学习者信息输入区" |
| 1:00 | 输入第一组 | 填"张三，本科，计算机，想学 LangGraph" | "我们输入第一组学习者信息" |
| 1:30 | 生成结果 | 点击生成按钮 | "Agent 1 首先诊断学习者的知识结构" |
| 2:00 | 诊断结果 | 展开知识盲区 | "可以看到，系统识别出了 5 个知识盲区" |
| ... | ... | ... | ... |

**要求：**
- 至少安排 3 组学习者对比演示（证明不同输入产生不同结果）
- 总时长控制在 5 分钟以内
- 旁白自然，不要太书面

---

## 👤 角色4 — Agent 1 学情诊断（主）

**负责文件：** `backend/src/agents/diagnosis.py`

**辅助角色5：** 测试 Agent 2 的生成内容

### 任务 4.1: 精调 Agent 1 的 system prompt（预计 3-4 小时）

**目标：** 诊断结果不是"你是中级水平"这种废话，而是具体的知识缺口——"你不懂状态机，所以学不会 LangGraph"这种。

**文件：** `backend/src/agents/diagnosis.py`

**具体步骤：**

1. **读懂现有 prompt（30 分钟）：**
   - 打开 `diagnosis.py`，找到 `SYSTEM_PROMPT` 和 `_build_prompt`
   - 把这两段贴给 AI："请解释这个 prompt 在做什么，每个部分的设计意图是什么"
   - 标注出可能需要改进的地方

2. **改进 prompt（核心工作）：**
   
   现有 prompt 的问题是：LLM 可能给出太泛的诊断（"你需要学习 Python 基础"）。你要让它更精细。

   **改进方向 A — 增加"前置依赖链"意识：**
   ```
   在 SYSTEM_PROMPT 里加一条：
   - 知识盲区不是"没学过的都缺"，而是"前置依赖链缺失"
     - 例：想学 LangGraph 但不知道状态机 → gap
     - 例：想学 RAG 但不知道向量 → gap
     - 例：不知道某个 API 具体参数名 → 这不是 gap，这是查表的事
   ```

   **改进方向 B — 增加置信度说明：**
   ```
   每个 skill_gap 的 confidence 要有区分：
   - confidence > 0.8: 前置测试直接证明
   - confidence 0.5-0.8: 从学历/经历推断
   - confidence < 0.5: 推测，需要进一步测试确认
   ```

   **改进方向 C — skill_gaps 优先级的判断更严格：**
   ```
   critical: 不学会这个，学习目标完全无法推进
   high: 学习目标的核心前置
   medium: 有助于更好理解，但不是阻塞性的
   low: 锦上添花
   ```

3. **修改 `_build_prompt` 方法：**
   - 确认使用 `re.search` 提取学习者信息而不是硬编码
   - 输出 JSON 的格式不变（和 Agent 2 约定的接口不能改）

---

### 任务 4.2: 构造测试用例 + 验证（预计 3 小时）

**具体步骤：**

1. **构造 5 组差异化学习者输入：**
   ```
   学习者 A: 职校毕业, 学餐饮管理, 完全零编码 → 学习目标: "学 Python 做数据分析"
   学习者 B: 本科计算机, 3年Java开发 → 学习目标: "学 LangGraph 做 AI Agent"
   学习者 C: 硕士机器学习, 熟悉 PyTorch → 学习目标: "学 LangGraph 部署到生产环境"
   学习者 D: 本科英语, 自学过 HTML/CSS → 学习目标: "学 Prompt Engineering"
   学习者 E: 博士计算机视觉, 5年研究经验 → 学习目标: "学多Agent协同架构设计"
   ```

2. **跑 Agent 1，记录每次的诊断结果：**
   - 用 `/api/generate` 调（不配 Key 用演示模式也可以）
   - 把 5 组诊断结果放在一个表格里对比

3. **检查诊断质量：**
   - 学习者 A 的 `recommended_difficulty` 是不是 "beginner"？
   - 学习者 E 的 `recommended_difficulty` 是不是 "advanced"？
   - 5 个人的 `skill_gaps` 列表是不是真的不同？（不是同一份改了关键词）
   - 每个 gap 的 `reason` 是否具体？（"没有编程基础"是好理由，"需要学习"是差理由）

4. **记录改进点：** 哪些诊断不合理的 → 回到步骤 2 修改 prompt → 再测

---

### 任务 4.3: 帮角色5 验证 Agent 2（预计 2 小时）

1. 把你的 5 组诊断结果给角色5
2. 角色5 用这些诊断来生成资源
3. 你检查：生成的内容是否真的对着诊断的 `skill_gaps`？（不是泛泛而谈）

---

## 👤 角色5 — Agent 2 知识生成（主）

**负责文件：** `backend/src/agents/generation.py`

**辅助角色4：** 测试 Agent 1 的诊断效果

### 任务 5.1: 去掉知识库约束，改 system prompt（预计 2 小时）

**目标：** Agent 2 现在靠 LLM 自身知识生成内容，不依赖外部知识库。

**文件：** `backend/src/agents/generation.py`（仓库已有参考代码）

**具体步骤：**

1. **看懂现有代码（30 分钟）：**
   - 找到 `SYSTEM_PROMPT` 和 `_generate_one()` 方法
   - 把这两段贴给 AI："请对比改进前后的区别，各有什么优劣"

2. **修改 system prompt（核心工作）：**

   删除这些内容（和 KB 相关的）：
   ```
   ❌ "基于领域知识库检索结果（retrieved_chunks），生成高保真的个性化学习资源"
   ❌ "每条专业断言必须引用知识库原文（citation）"
   ❌ "你不能编造不在知识库中的专业事实"
   ❌ "如果知识库没有覆盖某个知识点，请诚实标注'通用知识参考'"
   ```

   替换为：
   ```
   ✅ "用你的专业知识生成准确、实用的学习资源"
   ✅ "代码示例完整可运行，命令行标注操作系统"
   ✅ "内容必须准确——这是教育场景，教错了比不教更糟"
   ✅ "个性化体现在：解释深度适应难度等级，示例类型适应学习风格"
   ```

3. **改进 `_generate_one` 的 prompt 构建：**
   - 不同难度 → 不同要求：
     ```
     beginner: "多用生活类比，每行代码加注释，不假设任何前置知识"
     intermediate: "适当减少注释，引入进阶概念，假设学习者有基础编程能力"
     advanced: "精简解释，给高质量代码和架构思考，关注生产环境最佳实践"
     ```
   - 不同学习风格 → 不同要求：
     ```
     practice_first: "先给可运行的完整代码，再解释每段在做什么"
     theory_first: "先讲为什么需要这个技术、解决什么问题，再给代码"
     ```
   - `skill_gaps` 里 priority 为 critical 的知识点 → 这次生成必须覆盖
   - 资源类型不同 → 生成的内容结构明显不同：
     ```
     lecture: 有目录、有引言、有各小节、有总结
     guide: 有步骤1/2/3/4、每个步骤有命令或代码、有预期输出
     quiz: 有题目编号、4个选项、标注正确答案、有解析
     ```

---

### 任务 5.2: 生成质量验证（预计 3 小时）

1. 从角色4 拿 5 组诊断结果
2. 每组诊断 × 3 种资源类型 = 15 次生成
3. 用以下标准检查每次生成的质量：

   **准确性检查：**
   - [ ] 生成的代码示例语法正确吗？
   - [ ] 有事实性错误吗（比如"LangGraph 是 Google 开发的"）？
   - [ ] API 名称和参数对吗？

   **个性化检查：**
   - [ ] beginner 的内容真的有更多注释和比喻吗？
   - [ ] advanced 的内容真的更有深度吗？
   - [ ] practice_first 真的是先给代码再解释吗？

   **完整性检查：**
   - [ ] lecture 有目录结构吗？
   - [ ] guide 有分步操作吗？
   - [ ] quiz 有正确答案吗？

4. **记录问题：** 哪个 learner + 哪种资源 = 质量不达标 → 回到步骤 2 调整 prompt

---

## 👤 角色6 — 测试（主）+ Phase 2 辩论方案

**辅助角色2：** 测试 LLM 演示模式
**负责产出：** MVP 测试报告 + Phase 2 辩论协议设计草案

### 任务 6.1: 测试角色2 的演示模式（预计 2 小时，7/17-18）

**具体步骤：**
1. 角色2 代码写完后，你在**不配 API Key** 的环境下测试
2. 测 5 次诊断调用 + 5 次生成调用
3. 每次验证：
   - 返回的不是空 `{}`
   - JSON 的 key 是完整的（诊断有 `skill_gaps`，资源有 `content`）
   - 换不同的输入 → 模拟数据真的有变化（不是同一份数据反复返回）
4. 对比：配 Key 的返回 vs 不配 Key 的返回 → 格式是否一致？
5. 记录差异 → 发给角色2

---

### 任务 6.2: 写批量测试脚本（预计 2 小时，7/22）

**文件：** 新建 `backend/tests/test_mvp.py`

**具体步骤：**
1. 用 Python 的 `requests` 库写一个脚本
2. 脚本要能：
   - 读取预设的 5 组测试输入
   - 依次发送 `POST /api/generate`
   - 检查每次返回的 HTTP 状态码
   - 检查返回 JSON 里必需的 key 存在
   - 把结果打印成表格
3. 添加断言（assert）：
   ```python
   assert response.status_code == 200, f"期望200，返回{response.status_code}"
   assert "diagnosis" in data, "返回缺少 diagnosis"
   assert len(data.get("resources", [])) > 0, "返回没有资源"
   ```
4. 跑这个脚本 → 全部通过 → 发给角色7 执行

---

### 任务 6.3: 出 MVP 测试报告（预计 2 小时，7/24）

**文件：** 新建 `docs/MVP_TEST_REPORT.md`

**内容：**
1. 测试概览：测了多少组、多少次调用、通过率
2. 逐组结果：输入是什么、诊断结果摘要、生成资源质量评价
3. 发现的问题：按严重程度排序
4. 改进建议：给 Phase 2 的

---

### 任务 6.4: 设计 Phase 2 辩论协议草案（预计 3 小时，7/24-25）

**文件：** 阅读 `backend/src/debate/engine.py` → 设计改进方案

**要回答的问题：**
1. Agent 3 怎么从 Agent 2 的生成内容中提取"可验证的断言"？
2. Agent 3 发起的"质询"需要包含什么信息？（KB证据？推理链条？）
3. Agent 2 的"辩护"需要引用什么？（KB原文？还是说"我认为..."？）
4. 怎么判断辩论"达成了共识"？
5. 3 轮未共识 → escalate 之后怎么办？
6. 辩论协议的状态机怎么设计？（用什么图画出状态流转？）

**产出格式：** 一个 Markdown 文档（500-1000 字），回答以上 6 个问题

---

## 👤 角色7 — 测试执行 + Phase 2 评估方案（副）

**辅助角色6：** 测试用例执行
**负责产出：** 测试执行记录 + Phase 2 评估指标设计草案

### 任务 7.1: 设计 MVP 测试用例（预计 2 小时，7/19-21）

**文件：** 新建 `docs/MVP_TEST_CASES.md`

**具体步骤：**
1. 设计 5 组测试输入，每组包含：
   - 学习者基本信息（学历、专业、经验）
   - 学习目标
   - 选择的资源类型
   - **期望的诊断结果**（学习风格预判、难度预判、至少应该包含哪些知识盲区）
   - **期望的资源内容**（应该覆盖哪些知识点、不应该出现哪些错误）
2. 5 组要覆盖差异足够大的学习者：
   - 零基础 vs 有基础
   - 科班 vs 非科班
   - 入门目标 vs 进阶目标
   - 理论偏好 vs 实操偏好

---

### 任务 7.2: 执行测试 + 记录结果（预计 3 小时，7/22-24）

**具体步骤：**
1. 用角色6 写的测试脚本跑一遍
2. 跑完之后 **人工检查** 每组的实际输出：
   - 诊断结果符合预期吗？
   - 生成的资源是否真的覆盖了该学习者的知识盲区？
   - 有没有明显的事实性错误？
3. 把检查结果填到 `MVP_TEST_CASES.md` 的表格里

---

### 任务 7.3: 设计 Phase 2 三项指标评估方案（预计 3 小时，7/24-25）

**背景：** Phase 2 要评估三个硬指标：幻觉率 <5%、适配率 ≥85%、覆盖率 ≥90%。

**要回答的问题：**
1. **幻觉率怎么算？**
   - 谁来判定"这条断言是错的"？（Agent 3？人工？和 KB 比对？）
   - 什么算"一条断言"？（每句话？每个独立事实声明？）
   - 样本量要多大才有统计意义？

2. **适配率怎么算？**
   - 怎么判断"这个资源真的适合这个学习者"？
   - 是 Agent 3 判断难度匹配？还是学习者自评？还是测试成绩？

3. **覆盖率怎么算？**
   - 怎么统计"这个资源覆盖了哪些知识点"？
   - Agent 1 输出的 skill_gaps 怎么和 Agent 2 输出的资源对应？

**产出格式：** `docs/PHASE2_EVALUATION_PLAN.md`，500-1000 字，给出每个指标的计算公式和验证方法。

---

## 👤 角色8 — Streamlit 前端（主）

**负责文件：** `frontend/streamlit/app.py`（新建）

**辅助角色3：** UI 建议

### 任务 8.1: 搭前端骨架（预计 4-5 小时，7/17-22）

**目标：** 一个单页面 Streamlit 应用。

**文件：** `frontend/streamlit/app.py`（已有参考代码）

**具体步骤：**

1. **先跑通现有代码（30 分钟）：**
   ```bash
   pip install streamlit requests
   streamlit run frontend/streamlit/app.py
   ```
   浏览器打开 http://localhost:8501 → 看现在长什么样

2. **侧边栏表单（1.5 小时）：**
   需要这些输入控件：
   ```python
   name = st.text_input("姓名")
   education_level = st.selectbox("学历",
       ["high_school", "junior_college", "bachelor", "master", "phd"],
       format_func=lambda x: {"high_school": "高中", ...}[x]
   )
   major = st.text_input("专业")
   work_years = st.slider("工作年限", 0.0, 20.0, 1.0)
   industry = st.text_input("行业")
   positions = st.text_input("岗位（逗号分隔）")
   skills_used = st.text_input("技能（逗号分隔）")
   learning_goal = st.text_area("学习目标")
   resource_types = st.multiselect("资源类型",
       ["lecture", "guide", "quiz"],
       default=["lecture", "guide", "quiz"],
       format_func=lambda x: {"lecture": "定制讲义", "guide": "实操指南", "quiz": "分阶测试题"}[x]
   )
   generate_btn = st.button("生成个性化学习资源", type="primary")
   ```

3. **主区域展示（2 小时）：**
   用 `st.tabs` 做两个 tab：

   **Tab 1: 学情诊断**
   - 学习风格和推荐难度 → `st.metric`
   - 整体画像总结 → `st.write`
   - 知识盲区列表 → `st.expander`（每个 gap 一个展开块）
   - 知识掌握度 → `st.progress`（每个知识点一条进度条）

   **Tab 2: 学习资源**
   - 每个资源用 `st.expander` 展开
   - 资源内容用 `st.markdown` 渲染
   - 展开块的标题包含资源类型图标（讲义📖/指南🛠️/测试✏️）

4. **调通后端调用（1 小时）：**
   ```python
   if generate_btn:
       data = {
           "education_level": education_level,
           "major": major,
           ...
       }
       response = requests.post("http://localhost:8000/api/generate", json=data, timeout=120)
       if response.status_code == 200:
           result = response.json()
           st.session_state.result = result  # 存到 session 里，页面刷新不丢失
       else:
           st.error(f"生成失败: {response.text}")
   ```

5. **错误处理（30 分钟）：**
   - 后端没启动 → 提示"请先启动后端: `python -m uvicorn ...`"
   - 请求超时 → 提示"生成超时，请重试"
   - 返回数据为空 → 提示"未获取到数据，请检查 API Key 配置"

---

### 任务 8.2: UI 细节打磨（预计 2 小时，7/23-25）

1. 角色3 反馈的问题 → 逐条修
2. 确认三种资源类型的显示都正常
3. 确认不同学习者输入的切换流畅
4. 底部状态栏：显示"后端连接状态 🟢/🔴"

---

### 任务 8.3: 前端功能清单（预计 30 分钟，7/28）

**文件：** 新建 `frontend/streamlit/CHECKLIST.md`

列出前端所有功能点，每个打 ✅/❌。验收时对着清单逐条过。
