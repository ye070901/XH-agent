# 部署说明

> 领域知识个性化生成与多智能体协同决策系统（XH-202630）

本文档说明如何从零把本系统在本机跑起来，供评审复现验证。系统分**后端**（Python + FastAPI + ChromaDB）与**前端**（React + Vite）两部分，可独立启动。

---

## 一、环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.11 – 3.13 | 后端运行时 |
| Node.js | 18+（建议 20 LTS） | 前端构建 |
| npm | 9+ | 随 Node 附带 |

> Windows 一键启动：项目根目录双击 `start.bat`（自动建虚拟环境、装依赖、起后端），可跳过下面手工步骤。

---

## 二、后端部署

### 1. 创建虚拟环境并安装依赖

```bash
# 在项目根目录（XH-agent/）下
python -m venv .venv

# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt
# Linux / macOS
.venv/bin/pip install -r requirements.txt
```

### 2. 配置环境变量（.env）

```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```

然后编辑 `.env`，关键是 `LLM_API_KEY`：

- **演示模式（默认，无需联网）**：`LLM_API_KEY` 留空，系统返回模拟数据，用于快速跑通流程；
- **真实模式**：填入 DeepSeek API Key（或其他 OpenAI 兼容的 Key，改 `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_MODEL` 即可）。

```env
LLM_API_KEY=            # 留空 = 演示模式；填 sk-xxx = 真实调用
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

> ⚠️ `.env` 含密钥，已被 `.gitignore` 排除，**切勿提交或外传**。

### 3. 启动后端

```bash
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# Linux/macOS: .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

启动时后端会**增量同步知识库**：`data/raw/` 下的领域文档自动向量化进 ChromaDB（新文档新增、已改文档重建、未变文档跳过）。

### 4. 验证后端

- 健康检查：http://localhost:8000/health → 返回 `{"status":"healthy","kb_docs":N}`，`kb_docs` 为已入库文档数；
- 接口文档：http://localhost:8000/docs （FastAPI 自动生成的 Swagger）。

---

## 三、前端部署

```bash
cd frontend
npm ci          # 首次安装依赖（用 lock 文件锁定版本）
npm run dev     # 启动 Vite 开发服务器
```

打开 http://localhost:5173/ （方案 B 为默认入口）。前端通过 `/api` 代理到后端 8000 端口（`vite.config.ts` 已配置）。

---

## 四、离线部署注意事项（评审环境无外网时）

1. **Embedding 模型缓存**：后端用 ChromaDB 本地 embedding（`all-MiniLM-L6-v2`，约 83MB）。首次运行若需联网下载模型，离线环境应随包携带模型缓存（位于用户缓存目录的 `chroma/onnx_models/`），否则会降级为关键词检索。随提交包携带 ONNX 模型缓存可保证离线全功能。
2. **真实 LLM 依赖联网**：真实模式需访问 DeepSeek API，离线环境请用**演示模式**（`.env` 留空 `LLM_API_KEY`）。
3. **知识库数据**：`data/raw/` 是原始语料（提交包内含），`data/chroma/` 是派生的向量库（无需提交，启动时自动重建）。

---

## 五、常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `/health` 返回 `demo_mode:true` | `.env` 未填 `LLM_API_KEY` | 演示模式正常；要真实调用就填 Key |
| LLM 报 402 `Insufficient Balance` | API 账户余额不足 | 充值或更换 Key |
| `kb_docs=0` | `data/raw/` 空或未同步 | 确认 `data/raw/` 有文档，重启后端 |
| 端口 8000 被占用 | 已有后端在跑 | 换端口或先停掉旧进程 |
| 前端请求 404 | 代理未生效 | 确认后端已起、前端 `npm run dev` 在跑 |
| ChromaDB 报模型缺失 | embedding 模型未缓存 | 联网重跑一次，或携带 ONNX 缓存 |

---

## 六、一键脚本对照

| 平台 | 脚本 | 作用 |
|------|------|------|
| Windows | `start.bat` | 自动建 venv + 装依赖 + 起后端 |
| 任意 | `python main.py` | 直接启动（等价 uvicorn） |
