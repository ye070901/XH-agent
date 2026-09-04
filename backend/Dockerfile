FROM python:3.11-slim

WORKDIR /app

# 构建上下文已是仓库根（docker-compose build: .），不再整仓拷进 /app/backend。
# 只拷运行所需的根入口 + backend/ 目录（保持 backend.src.* 绝对导入的层级）。
COPY main.py /app/main.py
COPY backend /app/backend

# 安装运行依赖（与根目录 requirements.txt 一致）
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" openai chromadb pydantic pydantic-settings \
    python-dotenv loguru httpx rich python-multipart websockets \
    langgraph langchain langchain-openai langchain-anthropic

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
