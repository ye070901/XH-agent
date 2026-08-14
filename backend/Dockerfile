FROM python:3.11-slim

WORKDIR /app

# 保持 backend/ 目录层级，匹配代码中的 backend.src.* 绝对导入
COPY . /app/backend

# 安装运行依赖（与根目录 requirements.txt 一致）
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" openai chromadb pydantic pydantic-settings \
    python-dotenv loguru httpx rich python-multipart websockets \
    langgraph langchain langchain-openai langchain-anthropic

EXPOSE 8000

CMD ["uvicorn", "backend.src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
