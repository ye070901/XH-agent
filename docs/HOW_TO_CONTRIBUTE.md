# 队员代码提交指南

> 照着做，每一步都有截图可以对照。遇到问题在群里问角色1。

---

## 第一步：安装 Git

如果电脑上还没有 Git：

1. 打开 https://git-scm.com/downloads
2. 下载 Windows 版本
3. 安装时一路点"下一步"，全部默认选项即可
4. 安装完后，在桌面右键 → 选择 **"Open Git Bash Here"**，输入：

```bash
git --version
```

看到 `git version 2.xx.x` 就说明安装成功了。

---

## 第二步：克隆仓库到本地

打开 Git Bash，输入：

```bash
cd ~/Desktop
git clone https://github.com/ye070901/XH-agent.git
cd XH-agent
```

执行完后桌面上会出现 `XH-agent` 文件夹。

---

## 第三步：看懂你要改哪个文件

打开 `README.md`，找到自己的角色编号，看对应的文件路径。

| 角色 | 你只改这个文件 |
|------|--------------|
| 角色1 | `backend/src/graph/orchestrator.py` |
| 角色2 | `backend/src/llm/client.py` |
| 角色3 | `backend/src/knowledge/store.py` |
| 角色4 | `backend/src/agents/diagnosis.py` |
| 角色5 | `backend/src/agents/generation.py` |
| 角色6 | `backend/src/agents/audit.py` + `backend/src/debate/engine.py` |
| 角色7 | `backend/src/evaluation/metrics.py` |
| 角色8 | `frontend/src/` 整个目录 |

**其他文件不要改，除非角色1 让你改。**

---

## 第四步：打开你的任务说明

找到 `docs/roles/roleN-*.md`（N 是你的角色编号），从头读到尾。

里面有：
- 你的输入是什么（从 state 的哪个 key 读）
- 你的输出是什么（往 state 的哪个 key 写）
- 输出格式的 JSON 结构（必须完全一致）

---

## 第五步：创建你的分支

```bash
cd ~/Desktop/XH-agent
git checkout -b feature/你的模块名
```

例如：
- 角色4：`git checkout -b feature/agent-diagnosis`
- 角色5：`git checkout -b feature/agent-generation`

---

## 第六步：写代码（用 AI 辅助）

### 方法 1：用 Claude Code（推荐）

如果你装了 Claude Code，打开终端进入项目目录，输入：

```
我现在要实现 docs/roles/role4-diagnosis.md 里的任务。
先读一下 backend/src/schemas.py 的数据模型，
再读 backend/src/agents/base.py 的基类，
然后完善 backend/src/agents/diagnosis.py。
遵守 docs/INTERFACE_CONTRACT.md 里的接口约定。
```

AI 会自动读取相关文件后帮你写代码。

### 方法 2：用 ChatGPT / 网页版 Claude

1. 打开 `docs/roles/roleN-*.md`，复制全文
2. 打开 `backend/src/schemas.py`，复制全文
3. 打开 `backend/src/agents/base.py`，复制全文
4. 打开你自己的那个文件（如 `backend/src/agents/diagnosis.py`），复制全文
5. 粘贴到对话框里，加一句："请帮我完善这个 Agent 的实现。遵守接口契约。我的角色说明如下：[粘贴上面第1步的内容]"

---

## 第七步：配置 API Key（仅角色2/3/4/5/6/7 需要）

复制模板文件：

```bash
cp .env.example .env
```

然后用记事本打开 `.env`，把 `LLM_API_KEY=sk-your-key-here` 改成你自己的 Key。

角色2、3、4、5、6、7 需要配置，角色8（前端）不需要。

---

## 第八步：本地验证你的代码

在 Git Bash 里执行：

```bash
cd ~/Desktop/XH-agent/backend

# 1. 安装依赖（只做一次）
pip install -e ".[dev]"

# 2. 检查代码风格
ruff check src/

# 3. 检查接口契约
python ../scripts/check_contracts.py

# 4. 跑测试
python -m pytest tests/ -v
```

三条全部通过 → 可以提交。有报错 → 修完再提交。

---

## 第九步：提交并推送

```bash
cd ~/Desktop/XH-agent

# 添加你改的文件
git add backend/src/agents/diagnosis.py    # 改成你自己的文件路径

# 提交
git commit -m "角色4: 完成学情诊断Agent的prompt精调"

# 推送
git push origin feature/agent-diagnosis    # 改成你自己的分支名
```

---

## 第十步：在 GitHub 上创建 Pull Request（PR）

1. 打开 https://github.com/ye070901/XH-agent
2. 页面顶部会看到黄色提示条 "feature/xxx has recent pushes" → 点击 **"Compare & pull request"**
3. Base 选 `main`，Compare 选你自己的分支
4. 标题写清楚你做了什么
5. 点击 **"Create pull request"**
6. 等角色1 review 后合并

---

## 常见问题

### Q: `git push` 报错 "permission denied"

你需要先被加入仓库的 Collaborator。把你的 GitHub 用户名发给角色1，他会在仓库 Settings → Collaborators 里添加你。

### Q: `pip install` 报错

试试：
```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

### Q: 我的代码和别人的冲突了

告诉角色1，他来处理。不要在本地执行 `git merge`，除非你确定自己会。

### Q: 我改了 schemas.py 怎么办？

**不要改。** 如果确实需要加新字段，先在群里讨论，角色1 同意之后再改，改了之后在群里通知所有人。

### Q: 我写完发现别人也在改同一个文件

不会——因为我们每个人负责的文件不重叠。如果你发现和别人改了同一个文件，说明有人越界了。在群里确认。

---

## 操作速查

```bash
# 克隆（第一次）
git clone https://github.com/ye070901/XH-agent.git
cd XH-agent

# 创建分支（每次开始新任务）
git checkout -b feature/你的模块名

# 查看改了什么
git status

# 提交
git add 你的文件路径
git commit -m "描述你做了什么"

# 推送
git push origin feature/你的分支名

# 拉取最新代码（合并完PR之后）
git checkout main
git pull origin main
```
