# FastAPI 后端开发

## 什么是 FastAPI

FastAPI 是一个现代、高性能的 Python Web 框架，专为构建 API 而设计。它基于 Starlette 和 Pydantic，原生支持异步处理、自动生成 OpenAPI 文档和数据验证。

## 核心特性

### 自动文档生成
启动服务后自动生成 Swagger UI（/docs）和 ReDoc（/redoc），无需手动编写 API 文档。

### 类型安全
利用 Python 类型注解实现请求/响应的自动验证：

```python
from pydantic import BaseModel

class GenerateRequest(BaseModel):
    learning_goal: str
    education_level: str
    major: str
    resource_types: list[str]

@app.post("/api/generate")
async def generate(request: GenerateRequest):
    return {"status": "processing"}
```

### 异步支持
路由处理函数可以是 async 的，与 Agent 系统的异步 LLM 调用天然兼容。

## 项目中的 API 设计

### 接口结构
```
POST /api/generate          # 发起资源生成任务
GET  /api/task/{task_id}    # 查询任务状态
GET  /api/report/{learner_id}  # 获取学情报告
WS   /ws/{task_id}          # WebSocket 实时推送 Agent 通信
```

### 请求验证
使用 Pydantic 模型定义请求 schema，FastAPI 自动完成验证：
```python
class CreateProfileRequest(BaseModel):
    name: str
    education: Education
    experience: WorkExperience
    pretest_results: list[PretestResult] = []
    learning_goal: Optional[str] = None
```

### 错误处理
```python
from fastapi import HTTPException

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"message": "服务器内部错误", "detail": str(exc)}
    )
```

## 中间件配置

### CORS 配置
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 请求日志
通过 loguru 记录每个请求的处理时间、状态码。

## 与 LangGraph 编排器集成

```python
@app.post("/api/generate")
async def generate(request: GenerateRequest):
    learner_data = {
        "education_level": request.education_level,
        "major": request.major,
        "learning_goal": request.learning_goal,
    }
    result = await orchestrator.run(
        learner_data=learner_data,
        resource_types=request.resource_types
    )
    return {
        "status": result["status"],
        "diagnosis": result.get("diagnosis_result", {}),
        "resources": result.get("generated_resources", []),
        "audit": result.get("audit_result", []),
    }
```

## 部署建议

1. 使用 uvicorn 作为 ASGI 服务器
2. Nginx 反向代理处理静态文件和 HTTPS
3. Docker 容器化部署
4. 环境变量管理敏感配置（.env 文件）
