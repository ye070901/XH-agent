# Agent 4 保真修正 — 完整测试操作步骤

## 前置条件

- Python 3.10+
- 项目根目录: `e:\智训\XH-agent`
- 依赖已安装: `pip install -r backend/requirements.txt`

---

## 方式一：演示模式（零配置，无需 API Key，推荐首次验证）

> 原理：`LLM_API_KEY` 为空时，LLM Client 自动切换为演示模式，各 Agent 返回预置模拟数据。

### 1. 确认演示模式

```bash
cd e:\智训\XH-agent
python -c "from backend.src.config import settings; print('Demo mode:', settings.is_demo_mode)"
# 输出: Demo mode: True   ← 确认演示模式已激活
```

### 2. 启动后端服务

```bash
cd e:\智训\XH-agent
python -m uvicorn backend.src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

启动成功标志：
```
INFO:     Uvicorn running on http://0.0.0.0:8000
[Config] LLM: openai/gpt-4o
[Config] Demo Mode: True
```

### 3. 调用 /api/generate 测试完整 4 Agent 流水线

**Windows PowerShell:**
```powershell
curl.exe -X POST http://localhost:8000/api/generate `
  -H "Content-Type: application/json" `
  -d '{\"name\":\"测试用户\",\"education_level\":\"bachelor\",\"major\":\"计算机科学\",\"work_years\":2,\"industry\":\"互联网\",\"positions\":[\"Python后端开发\"],\"skills_used\":[\"Python\",\"FastAPI\",\"Docker\"],\"learning_goal\":\"学习LangGraph构建多Agent协同系统\",\"resource_types\":[\"lecture\"]}'
```

**Git Bash（项目自带）:**
```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "name": "测试用户",
    "education_level": "bachelor",
    "major": "计算机科学",
    "work_years": 2,
    "industry": "互联网",
    "positions": ["Python后端开发"],
    "skills_used": ["Python", "FastAPI", "Docker"],
    "learning_goal": "学习LangGraph构建多Agent协同系统",
    "resource_types": ["lecture"]
  }'
```

### 4. 验证响应格式

期望 HTTP 200 响应，包含以下 5 个顶层字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | `string` | UUID 任务ID |
| `status` | `string` | `"completed"` |
| `diagnosis` | `dict` | Agent 1 学情诊断结果（knowledge_map / skill_gaps / learning_style / recommended_difficulty / summary） |
| `resources` | `list[dict]` | Agent 2 生成的原始学习资源（title / content / citations / difficulty_level / key_takeaways） |
| `audit` | `list[dict]` | Agent 3 审核报告（verdict / issues） |
| `corrected_resources` | `list[dict]` | **Agent 4 修正后的资源（含 `_was_corrected` / `_correction_summary`）** |
| `correction_stats` | `dict` | **修正统计（total_resources / errors_fixed / warnings_addressed / infos_applied / correction_time_ms）** |
| `agent_log` | `list[dict]` | 完整执行日志（按 agent 分组） |

### 5. 健康检查

```bash
curl http://localhost:8000/health
# 返回: {"status":"healthy","llm":"openai/gpt-4o","demo_mode":true}
```

---

## 方式二：真实模式（需 DeepSeek API Key）

### 1. 配置 .env 文件

```bash
cd e:\智训\XH-agent
cp .env.example .env
```

编辑 `.env`，填入 DeepSeek API Key：
```ini
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 2. 确认真实模式

```bash
python -c "from backend.src.config import settings; print('Demo mode:', settings.is_demo_mode)"
# 输出: Demo mode: False   ← 确认真实模式已激活
```

### 3. 启动后端（同演示模式）

```bash
python -m uvicorn backend.src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 调用 /api/generate（同演示模式 curl 命令）

---

## 方式三：Python 脚本直接验证（不走 HTTP）

### 测试完整 4 Agent 流水线

```bash
cd e:\智训\XH-agent
python -c "
import sys, asyncio
sys.path.insert(0, '.')
from backend.src.graph.orchestrator import workflow_engine

async def test():
    result = await workflow_engine.run(
        learner_data={
            'education_level': 'bachelor',
            'major': '计算机科学',
            'work_years': 2,
            'industry': '互联网',
            'positions': ['Python后端开发'],
            'skills_used': ['Python', 'FastAPI', 'Docker'],
            'learning_goal': '学习LangGraph构建多Agent协同系统',
        },
        resource_types=['lecture'],
    )
    
    print('=== 4 Agent 流水线测试 ===')
    print(f'Status: {result.get(\"status\")}')
    print(f'Diagnosis keys: {list(result.get(\"diagnosis_result\", {}).keys())}')
    print(f'Generated resources: {len(result.get(\"generated_resources\", []))}')
    print(f'Audit results: {len(result.get(\"audit_result\", []))}')
    print(f'Corrected resources: {len(result.get(\"corrected_resources\", []))}')
    
    stats = result.get('correction_stats', {})
    print(f'\nCorrection Stats:')
    print(f'  Total resources: {stats.get(\"total_resources\")}')
    print(f'  Resources corrected: {stats.get(\"resources_corrected\")}')
    print(f'  Errors fixed: {stats.get(\"errors_fixed\")}')
    print(f'  Warnings addressed: {stats.get(\"warnings_addressed\")}')
    print(f'  Infos applied: {stats.get(\"infos_applied\")}')
    print(f'  Time: {stats.get(\"correction_time_ms\")}ms')
    
    # 验证修正后资源
    corrected = result.get('corrected_resources', [])
    if corrected:
        r = corrected[0]
        print(f'\nCorrected Resource:')
        print(f'  Title: {r.get(\"title\", \"\")[:80]}')
        print(f'  Was Corrected: {r.get(\"_was_corrected\")}')
        print(f'  Summary: {r.get(\"_correction_summary\", \"\")[:100]}')
    
    # 验证流水线
    agent_names = []
    for e in result.get('agent_log', []):
        if 'agent' in e:
            agent_names.append(e['agent'])
    
    expected = ['diagnosis', 'generation', 'audit', 'correction']
    # 取最后4个匹配项
    matched = [n for n in agent_names if n in expected]
    print(f'\nPipeline: {\" -> \".join(matched[-4:]) if len(matched) >= 4 else \"INCOMPLETE\"}')
    print(f'Verdict: {\"PASS\" if result.get(\"status\") == \"completed\" else \"FAIL\"}')

asyncio.run(test())
"
```

### 单独测试 Agent 4 模块（模拟错误修正）

```bash
cd e:\智训\XH-agent
python -c "
import sys, asyncio
sys.path.insert(0, '.')
from backend.src.agents.agent4 import CorrectionAgent

async def test():
    agent = CorrectionAgent()
    state = {
        'diagnosis_result': {
            'summary': '学习LangGraph',
            'recommended_difficulty': 'beginner',
            'learning_style': 'theory_first',
            'skill_gaps': [],
        },
        'generated_resources': [{
            'resource_id': 'test-1',
            'resource_type': 'lecture',
            'title': 'LangGraph入门',
            'content': '# LangGraph入门\n\nLangGraph是Google开发的图状态管理框架。\n\n## 核心概念\nStateGraph是核心抽象。',
            'difficulty_level': 'beginner',
            'citations': [],
            'key_takeaways': [],
        }],
        'audit_result': [{
            'verdict': 'needs_revision',
            'issues': [
                {
                    'severity': 'error',
                    'detail': 'LangGraph不是Google开发，是LangChain团队开发',
                    'kb_evidence': 'LangGraph is a library built by the LangChain team',
                },
                {
                    'severity': 'warning',
                    'detail': '缺少StateGraph三要素说明',
                },
                {
                    'severity': 'info',
                    'detail': '建议加入生活类比',
                },
            ],
        }],
        'retrieved_chunks': [
            {
                'doc_id': 'kb_001.md',
                'chunk_index': 2,
                'content': 'LangGraph is a library built by the LangChain team for building stateful, multi-actor applications with LLMs.',
                'relevance_score': 0.95,
            },
        ],
    }
    
    result = await agent.run(state)
    print('=== Agent 4 单独测试 ===')
    print(f'Status: {result.get(\"status\")}')
    
    stats = result.get('correction_stats', {})
    print(f'Errors fixed: {stats.get(\"errors_fixed\")}')
    print(f'Warnings addressed: {stats.get(\"warnings_addressed\")}')
    print(f'Infos applied: {stats.get(\"infos_applied\")}')
    
    corrected = result.get('corrected_resources', [])
    if corrected:
        r = corrected[0]
        content = r.get('content', '')
        print(f'Title: {r.get(\"title\", \"\")}')
        print(f'Was Corrected: {r.get(\"_was_corrected\")}')
        # 验证演示模式修正：Google → LangChain
        has_google = 'Google' in content and 'LangGraph' in content
        has_langchain = 'LangChain' in content
        print(f'Google attribution removed: {not has_google}')
        print(f'LangChain attribution added: {has_langchain}')
    
    logs = result.get('correction_log', [])
    print(f'Correction log entries: {len(logs)}')
    for log in logs:
        print(f'  [{log[\"severity\"]}] {log[\"action\"]}: {log.get(\"original_text\", \"\")[:60]}...')

asyncio.run(test())
"
```

---

## 方式四：Agent 4 模块自带的 demo() 函数

`backend/src/agents/agent4.py` 文件末尾包含注释掉的 `demo()` 函数，取消注释即可独立运行：

```bash
cd e:\智训\XH-agent
python -c "
import sys, asyncio
sys.path.insert(0, '.')
from backend.src.agents.correction import CorrectionAgent

async def demo():
    agent = CorrectionAgent()
    state = {
        'diagnosis_result': {
            'summary': '学习 LangGraph 开发 AI Agent',
            'recommended_difficulty': 'beginner',
            'learning_style': 'theory_first',
            'skill_gaps': [
                {'priority': 'critical', 'topic': 'LangGraph 状态管理',
                 'current_level': 0.1, 'target_level': 0.9,
                 'reason': '不清楚图状态流转机制'},
            ],
        },
        'generated_resources': [{
            'resource_id': 'res-001', 'resource_type': 'lecture',
            'title': 'LangGraph 入门讲义',
            'content': '# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的图状态管理框架。\n\n## 核心概念\nStateGraph 让你用状态字典在节点间传递数据。\n',
            'difficulty_level': 'beginner', 'citations': [],
            'key_takeaways': ['理解 LangGraph', '掌握 StateGraph'],
        }],
        'audit_result': [{
            'verdict': 'needs_revision',
            'issues': [
                {'severity': 'error',
                 'detail': 'LangGraph 不是 Google 开发的，是 LangChain 团队开发的',
                 'kb_evidence': 'LangGraph is a library built by the LangChain team'},
                {'severity': 'warning',
                 'detail': '缺少对 StateGraph 三个要素的逐一说明'},
                {'severity': 'info',
                 'detail': '建议在引言中加入一个生活类比帮助理解'},
            ],
        }],
        'retrieved_chunks': [
            {'doc_id': 'langgraph_intro.md', 'chunk_index': 2,
             'content': 'LangGraph is a library built by the LangChain team for building stateful, multi-actor applications with LLMs.',
             'relevance_score': 0.95},
            {'doc_id': 'langgraph_intro.md', 'chunk_index': 5,
             'content': 'StateGraph 的三个核心要素：节点（Node）定义处理逻辑、边（Edge）定义流转方向、状态字典（State）传递上下文数据。',
             'relevance_score': 0.90},
        ],
    }
    result = await agent.run(state)
    print(f'修正完成: {len(result.get(\"corrected_resources\", []))} 个资源')
    print(f'修正统计: {result.get(\"correction_stats\", {})}')
    if result.get('correction_log'):
        print(f'修正日志: {len(result[\"correction_log\"])} 条')

asyncio.run(demo())
"
```

---

## 验收检查清单

| 序号 | 检查项 | 验证方法 |
|------|--------|---------|
| 1 | Agent 1 诊断正常 | `diagnosis` 字段含 `knowledge_map` + `skill_gaps` + `learning_style` + `recommended_difficulty` |
| 2 | Agent 2 生成正常 | `resources` 列表非空，每个资源含 `title` + `content` + `difficulty_level` + `key_takeaways` |
| 3 | Agent 3 审核正常 | `audit` 列表长度 = 资源数，每个报告含 `verdict` + `issues` |
| 4 | Agent 4 修正正常 | `corrected_resources` 列表非空，含 `_was_corrected` + `_correction_summary` |
| 5 | 修正统计完整 | `correction_stats` 含 `total_resources` / `errors_fixed` / `warnings_addressed` / `infos_applied` / `correction_time_ms` |
| 6 | 流水线顺序正确 | `agent_log` 中 agent 出现顺序: diagnosis → generation → audit → correction |
| 7 | 服务状态正常 | `GET /health` 返回 `{"status": "healthy"}` |
| 8 | 修正日志可追踪 | `correction_log` 每条含 `resource_id` / `severity` / `action` / `correction_basis` |

---

## 常见故障排查

| 症状 | 可能原因 | 解决方案 |
|------|---------|---------|
| `ModuleNotFoundError: No module named 'backend'` | 未从项目根目录运行 | `cd e:\智训\XH-agent` 后再运行 |
| `LLM 调用超时` | DeepSeek API 响应慢 | 增大 `.env` 中 `LLM_TIMEOUT_SECONDS=180` |
| `LLM 认证失败` | API Key 无效 | 检查 `.env` 中 `LLM_API_KEY` 是否正确 |
| `502 Bad Gateway` | 后端未启动 | 先启动 `uvicorn` |
| 修正后仍有错误 | 演示模式做的模拟修正 | 真实模式 + 有效 API Key 可获得准确的 LLM 修正 |
