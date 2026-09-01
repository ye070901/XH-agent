# 改动范围文档 —— 遗留清理（2026-09-01）

> 性质：三期遗留技术债「低风险清理」，均为**补充 / 收口**性质，不触碰评测用例、画像、接口契约核心逻辑。

## 一、提交清单

| 提交号 | 类型 | 改动文件 | 差异 |
|---|---|---|---|
| `5c61fef` | refactor | `backend/src/schemas.py` | −2 行 |
| `46cdfc7` | feat | `data/core_knowledge_map.json` | +138 / −1 行 |

远端：`main` 已推送同步（HEAD = `46cdfc7`）。工作区干净。

## 二、改动范围明细

### 1. 移除死枚举 `CASE_STUDY` / `MICRO_PROJECT`（`5c61fef`）

- **文件**：`backend/src/schemas.py`
- **内容**：从 `ResourceType` 枚举删除 `CASE_STUDY = "case_study"`、`MICRO_PROJECT = "micro_project"` 两个成员。
- **依据**：全仓库检索（除 `.venv` / `node_modules` / `.git` / `data/raw`）确认二者**零引用**——前端资源类型列表 `lecture/guide/quiz/project/pitfall_guide` 不含二者；后端生成管线、`client.py`、测试、数据均未使用。
- **影响**：接口契约变更（枚举成员减少），**需全员周知**；无运行时回归（无任何发送方使用这两个值，Pydantic 校验不会因删除而 422）。

### 2. 新增 `K12「AI 机器人与智能应用」` 知识域（`46cdfc7`）

- **文件**：`data/core_knowledge_map.json`（图谱版本 `2.0` → `2.1`）
- **内容**：新增领域 `K12`，把此前**全部未映射**的 `data/raw/K4_ai_robotics_{basic,practical}/` 下 **27 篇**素材（5 基础 K4B + 22 实战 K4P）落图，归为 **8 个 `standard` 级知识点**：

| 知识点 ID | topic | 映射文档数 |
|---|---|---|
| K12-STANDARD-001 | AI 视觉基础 | 2（K4B） |
| K12-STANDARD-002 | AI 机器人系统架构与部署 | 3（K4B） |
| K12-STANDARD-003 | AI 视觉标定与引导 | 5（K4P） |
| K12-STANDARD-004 | AI 仿真与 sim2real | 3（K4P） |
| K12-STANDARD-005 | AI 预测性维护 | 1（K4P） |
| K12-STANDARD-006 | AI 安全与 PLC 集成 | 2（K4P） |
| K12-STANDARD-007 | AI 实时性能与运动规划 | 3（K4P） |
| K12-STANDARD-008 | 行业 AI 应用场景 | 8（K4P） |

- **影响**：只读图谱多一个域；`standard` 级不计入 42 个 counted 点，**零评测回归**（详见第三节）。

## 三、零回归论证

1. **不触发评测重生成**：`counted_levels` 只含 `core/high`，`build_phase3_dataset.counted_knowledge_points()` 过滤 standard → 仍返回 42，`meta.case_count=424` 不变。
2. **不污染 KB 对齐率**：`metrics._extract_core_aliases` 的 `_TARGET_PRIORITIES = {critical, high, core}`，standard 别名不进字典，对齐打分无变化。
3. **前端零改动**：`vaultshield-hero.tsx` 用 `domains.map(...)` 通用渲染，无硬编码 K1–K11，仅多一个节点；`GET /api/knowledge/kb_core_map` 只读透传无 schema 校验。
4. **无悬空引用**：27 篇路径全部存在（`data/raw/` 文件未动，只新增指向它们的图谱边）。

## 四、全链路自检结果（全绿 ✅）

| 链路 | 检查项 | 结果 |
|---|---|---|
| 数据层 | JSON 合法性 / 结构 | ✅ 12 领域 / 53 知识点（core 21 + high 21 + standard 11）/ counted 42 |
| | 悬空引用 | ✅ 0 悬空 |
| | K4B / K4P 覆盖 | ✅ 5/5 + 22/22 全映射、无重复 |
| 评测链路 | `counted_knowledge_points()` | ✅ 返回 42（standard 排除） |
| | `_extract_core_aliases` | ✅ standard 不进别名字典 |
| | phase3 用例数 | ✅ 仍 424 |
| 后端 | `ruff check .` | ✅ All checks passed |
| | `check_hallucination.py` | ✅ 0 编造符号 |
| | `check_contracts.py` | ✅ ruff format + 模块导入 全通过 |
| | `pytest` | ✅ 305 passed |
| 前端 | `npm run build`（tsc + vite） | ✅ 1935 modules / 1.86s |
| 安全 | 改动内容含 `sk-` 密钥 | ✅ 无 |
| Git | 工作区 / 远端同步 | ✅ 干净、已同步 |

## 五、明确不做（out of scope）

- **K12 升格 `core/high` 进正式评测**（Stage 2）：需从中挑 3–5 点升 counted + `build_phase3_dataset.py` 补用例 + 更新 meta 计数，属「大改评测映射」，**演示冲刺勿做**，留待独立排期 + 负责人（Arch-L）确认 topic 命名。
- 不改评测用例、不改画像（learner_profiles）、不改 `schemas.py` 其他枚举、不改 `data/raw/` 下任何文档。

## 六、复核方式

```bash
# 查看本次全部改动
git diff 5c61fef^..46cdfc7

# 悬空引用 + 结构校验
../.venv/Scripts/python.exe -c "import json,os; d=json.load(open('data/core_knowledge_map.json',encoding='utf-8')); pts=[k for x in d['domains'] for k in x['knowledge_points']]; print('域',len(d['domains']),'点',len(pts),'悬空',[s for k in pts for s in k['source_documents'] if not os.path.exists(s)])"

# 后端全量测试
cd backend && ../.venv/Scripts/python.exe -m pytest -q

# 前端构建
cd frontend && npm run build
```
