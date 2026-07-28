# Python async/await 异步编程

## 为什么需要异步

在构建 AI Agent 系统时，大量的操作是 I/O 密集型的：LLM API 调用、数据库查询、文件读写、网络请求。同步执行这些操作会导致 CPU 大量时间浪费在等待上。异步编程允许在等待 I/O 时切换到其他任务，大幅提升系统吞吐量。

## 核心概念

### async / await
```python
async def fetch_data():
    result = await some_io_operation()
    return result
```

- `async def` 定义一个协程函数
- `await` 暂停当前协程，等待异步操作完成
- 协程不会阻塞线程

### 事件循环（Event Loop）
事件循环是异步编程的核心调度器。它维护一个任务队列，在任务等待时切换到其他任务。

```python
import asyncio

async def main():
    # 并发执行三个任务
    results = await asyncio.gather(
        task1(),
        task2(),
        task3()
    )
```

## 在 Agent 系统中的实际应用

### 并发 LLM 调用
当需要同时调用多个 Agent 时，并发比串行快很多：

```python
async def run_all_agents(state):
    # 并发执行诊断和检索
    diagnosis, kb_results = await asyncio.gather(
        agent1.process(state),
        knowledge_base.query(state["query"])
    )
```

### 流式输出
```python
async for chunk in llm.stream_response(prompt):
    yield chunk
```

### 超时控制
```python
try:
    result = await asyncio.wait_for(
        llm.call(prompt),
        timeout=120  # 120 秒超时
    )
except asyncio.TimeoutError:
    result = fallback_response()
```

## 常见陷阱

### 不要在协程中使用阻塞调用
```python
# 错误: requests 是同步库，会阻塞事件循环
response = requests.get(url)

# 正确: 使用异步 HTTP 库
response = await httpx.AsyncClient().get(url)
```

### 正确使用 asyncio.gather
`asyncio.gather` 允许并发执行多个协程，但如果其中一个抛出异常，默认会取消其他任务。使用 `return_exceptions=True` 来隔离错误。

### 避免在 async 函数中执行 CPU 密集型计算
CPU 密集型计算会阻塞事件循环。应使用 `asyncio.to_thread()` 将其移到线程池：

```python
result = await asyncio.to_thread(cpu_intensive_function, data)
```

## FastAPI 中的异步

FastAPI 原生支持异步路由处理函数：

```python
@app.post("/api/generate")
async def generate(request: GenerateRequest):
    result = await orchestrator.run(request)
    return result
```

数据库操作也应使用异步驱动（如 asyncpg 替代 psycopg2）。
