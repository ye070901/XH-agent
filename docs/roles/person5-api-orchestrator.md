# 人5：API 入口 + 编排器

## 你要做什么

两个文件，都只有几十行。

### 1. 编排器 — `graph/orchestrator.py`

把人2、人3、人4 的 Agent 串起来。

```python
state = {"learner_data": ..., "resource_types": [...]}

# Step 1
state.update(await agent1.process(state))

# Step 2
state.update(await agent2.process(state))

# Step 3
state.update(await agent3.process(state))

return state
```

### 2. API 入口 — `api/main.py`

POST /api/generate：收前端 JSON → 转成 learner_data → 调编排器 → 打包返回。

```python
@app.post("/api/generate")
async def generate(request: dict):
    learner_data = {
        "education_level": request.get("education_level", "bachelor"),
        "major": request.get("major", ""),
        ...
    }
    result = await workflow_engine.run(learner_data=learner_data, resource_types=...)

    return {
        "diagnosis": result["diagnosis_result"],
        "resources": result["generated_resources"],
        "audit": result["audit_result"],
    }
```

## 你怎么测

```bash
python -m uvicorn src.api.main:app --port 8000

curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"learning_goal":"学Python","education_level":"bachelor","major":"计算机","skills_used":["Python"],"resource_types":["lecture"]}'
```

HTTP 200，返回 JSON 含 diagnosis + resources + audit 三个字段。
