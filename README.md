# 领域知识个性化生成与多智能体协同决策系统

题目编号：XH-202630 | 发榜单位：上海云之脑智能科技有限公司

---

## 前提条件（接收方需要自己准备）

| 你需要有 | 怎么获取 |
|----------|----------|
| **Python 3.12+** | https://www.python.org/downloads/ |
| **Node.js 20+** | https://nodejs.org/ (选LTS版本) |
| **Git** | https://git-scm.com/downloads |
| **DeepSeek API Key** | https://platform.deepseek.com/ 注册 → 充值10元 → API Keys |
| **Docker Desktop**（可选） | https://www.docker.com/products/docker-desktop/ |

---

## 快速启动（5分钟）

```bash
# 1. 安装后端依赖
cd agent-decision-system
pip install -r requirements.txt

# 2. 配置API Key
cp .env.example .env
# 用记事本打开 .env，把 LLM_API_KEY=sk-xxx 改成你自己的DeepSeek Key

# 3. 启动后端
cd backend
python -m uvicorn app.main:app --reload --port 8000

# 4. 另一个终端，安装前端依赖
cd frontend
npm install

# 5. 启动前端
npm run dev

# 6. 打开浏览器 → http://localhost:3000
```

---

## 验证是否跑通

```bash
# 跑测试（不需要API Key也能跑通15个）
cd agent-decision-system
python -m pytest backend/tests/test_agents.py -v
```

看到 **15 passed** 就说明后端代码没问题。

---

## 项目结构

```
agent-decision-system/
├── schemas.py                  # ⭐ 全员统一的接口定义
├── requirements.txt            # Python依赖
├── docker-compose.yml          # 生产环境一键部署
├── .env.example                # 环境变量模板
│
├── backend/
│   ├── app/
│   │   ├── main.py             # 入口
│   │   ├── core/config.py      # 配置
│   │   ├── agents/             # 5个Agent
│   │   │   ├── diagnosis.py    #   学情诊断
│   │   │   ├── generator.py    #   知识生成
│   │   │   ├── reviewer.py     #   审核裁判
│   │   │   ├── planner.py      #   路径规划
│   │   │   └── feedback.py     #   交互反馈
│   │   ├── debate/engine.py    # 辩论引擎
│   │   ├── knowledge/rag.py    # RAG知识库
│   │   ├── workflow/graph.py   # LangGraph工作流
│   │   ├── api/routes.py       # REST + WebSocket
│   │   └── models/db.py        # 数据库
│   └── tests/test_agents.py    # 15个单元测试
│
└── frontend/
    └── src/pages/
        ├── ProfilePage.tsx      # 画像录入
        ├── GeneratePage.tsx     # Agent协同生成 + 实时可视化
        ├── ResourcePage.tsx     # 资源展示
        ├── QuizPage.tsx         # 答题 + 反馈
        └── ReportPage.tsx       # 学情报告
```

---

## 两个必须改的东西

| 文件 | 改什么 |
|------|--------|
| `.env` | `LLM_API_KEY=你的DeepSeek key` |
| `schemas.py` | 不需要改，但如果加了新字段，全员同步 |

---

## 注意事项

- 后端代码在不填API Key时也能启动和跑测试，但调用Agent会返回空结果
- 向量数据库Milvus没装也能跑，会自动切换到内存模式
- 前端没装依赖前页面是白的，先 `npm install`
- 如果端口8000被占用，改 `uvicorn` 的 `--port` 和 `frontend/vite.config.ts` 里的 proxy 目标
- DeepSeek API 充值10块钱够开发用一个月
