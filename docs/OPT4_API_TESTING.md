# Opt-4 API 与 Phase 3 测试方案

> 适用版本：Phase 3 v1.0  
> 责任边界：Opt-4 负责指标计算、前置测试采集、画像 SQLite 持久化和可复现评测；前端 UI 已移交 K3。  
> 硬约束：现有 `POST /api/generate` 入参、出参和路由均不改变。

## 1. 交付物概览

| 交付物 | 路径 | 用途 |
| --- | --- | --- |
| 三项指标实现 | `backend/src/evaluation/metrics.py` | 确定性计算幻觉率、适配率、覆盖率 |
| 前置测试题库 | `data/evaluation/pretest_questions.json` | 12 题、固定 120 分，评分后映射 `pretest_results` |
| 核心知识点清单 | `data/core_knowledge_map.json` | 覆盖率的外部真值；仅 `core/high` 计分 |
| 学习者画像真值 | `data/evaluation/learner_profiles.json` | 3 组差异化画像及预先确定的难度/风格 |
| 测试用例全集 | `data/evaluation/phase3_test_cases.json` | 54 正向 + 4 负向，不包含模型输出或实测指标 |
| 人工金标准模板 | `data/evaluation/gold_labels.template.json` | 空模板；复制为 `gold_labels.json` 后人工填写 |
| 数据集生成/校验 | `scripts/build_phase3_dataset.py`、`scripts/validate_phase3_dataset.py` | 可复现构建和发布门禁 |
| 输出采集/离线评测 | `scripts/collect_phase3_outputs.py`、`scripts/run_phase3_evaluation.py` | 原始输出与评分分离，防止篡改真值 |

## 2. 前置测试 API

### 2.1 获取公开题目

`GET /api/pretests/questions`

响应包含 `meta` 和 `questions`。公开响应会移除 `correct_answer` 与 `explanation`，避免答题前泄露答案。

### 2.2 提交并评分

`POST /api/pretests/score`

请求示例：

```json
{
  "learner_id": "learner_demo_001",
  "answers": [
    {"question_id": "PT-K1-001", "answer": "B"},
    {"question_id": "PT-K2-001", "answer": "A"}
  ]
}
```

响应核心字段：

```json
{
  "learner_id": "learner_demo_001",
  "total_score": 20.0,
  "max_score": 120.0,
  "percentage": 16.67,
  "topic_scores": {
    "机器人坐标系": 50.0,
    "运动指令": 0.0,
    "RobotStudio仿真": 50.0,
    "ROS2/Gazebo仿真": 0.0,
    "SRVO-068数据传输故障": 0.0,
    "安全急停链路": 0.0
  },
  "pretest_results": [
    {
      "test_name": "工业机器人编程调试前置测试",
      "total_score": 20.0,
      "max_score": 120.0,
      "topic_scores": {
        "机器人坐标系": 50.0,
        "运动指令": 0.0,
        "RobotStudio仿真": 50.0,
        "ROS2/Gazebo仿真": 0.0,
        "SRVO-068数据传输故障": 0.0,
        "安全急停链路": 0.0
      }
    }
  ],
  "details": []
}
```

评分是纯规则：每题 10 分，未答题计 0 分，所有知识点按固定分母换算百分比。前端应把响应中的 `pretest_results` 原样放入后续 `/api/generate` 请求，不要自行重算。

## 3. 学习者画像持久化 API

以下 6 个操作均挂在 `/api/profiles`。保存只发生在用户点击“认可，保存画像”后；“继续修改”不得调用保存接口。

| 方法 | 路径 | 说明 | 成功状态 |
| --- | --- | --- | --- |
| POST | `/api/profiles` | 保存一份完整画像快照 | `201` |
| GET | `/api/profiles?learner_id=&limit=50&offset=0` | 按 `updated_at` 倒序分页列出 | `200` |
| GET | `/api/profiles/{profile_id}` | 获取单份完整快照 | `200` |
| DELETE | `/api/profiles/{profile_id}` | 删除单份快照 | `200` |
| GET | `/api/profiles/settings/cleanup` | 获取自动清理设置 | `200` |
| PUT | `/api/profiles/settings/cleanup` | 更新自动清理设置 | `200` |

保存请求（`learner_id` 可选；未提供时服务端生成 `learner_<uuid>`，并在响应中返回）：

```json
{
  "learner_id": "learner_demo_001",
  "profile": {
    "name": "张三",
    "knowledge_map": {
      "机器人坐标系": {"level": 0.4, "confidence": 0.8, "evidence": "前置测试"}
    },
    "skill_gaps": [
      {"topic": "TCP标定", "priority": "high", "current_level": 0.2, "target_level": 0.8}
    ],
    "learning_style": "practice_first",
    "recommended_difficulty": "beginner"
  },
  "source_task_id": "task_demo_001",
  "label": "首次认可画像"
}
```

清理设置请求：

```json
{
  "max_profiles": 100,
  "cleanup_time": "03:00",
  "enabled": true
}
```

`cleanup_time` 使用服务器本地时间的 24 小时 `HH:MM`。启用清理时，更新数量上限会立即删掉超限的最旧记录；后台任务每天在设定时间按 `updated_at` 保留最新记录。不存在的 `profile_id` 返回 `404`，字段校验失败返回 `422`。

### 3.1 SQLite 表结构

数据库默认位于 `data/learner_profiles.db`，运行时自动创建，不提交仓库。

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `learner_profiles` | `profile_id`、`learner_id`、`name`、`profile_json`、`source_task_id`、`label`、`created_at`、`updated_at` | 保存认可后的完整 JSON 快照；K1 回写时刷新 `updated_at` |
| `cleanup_config` | `singleton_id=1`、`max_profiles`、`cleanup_time`、`enabled`、`updated_at` | 单例清理配置 |

SQLite 操作通过 `asyncio.to_thread` 执行，使用短连接、WAL 和 `busy_timeout`，避免阻塞 FastAPI 事件循环。

## 4. 三项指标与真值来源

### 4.1 幻觉率 `< 5%`

```text
幻觉率 = (hallucination + unverifiable) / 有效事实断言总数
```

- `accurate`、`hallucination`、`unverifiable` 进入分母。
- `skip` 仅用于过渡句、修辞或引导语，不进入分母。
- 未知标签保守计为 `unverifiable`。
- 没有任何事实断言时不自动通过。
- 最终资源中的 `unverifiable` 按 Phase 3 D1 删除，而不是保留或编造。

### 4.2 适配准确率 `>= 85%`

```text
适配率 = (难度匹配 + 风格匹配) / 2
难度：同级=1，相差1级=0.5，相差2级=0
```

评分只使用 `learner_profiles.json` 中预先写好的 `expected_profile`。禁止从本次模型诊断结果回填“应得难度/风格”，否则等同模型给自己打分。

### 4.3 核心知识点覆盖率 `>= 90%`

```text
覆盖率 = 正文实际覆盖的 critical/high 盲区 / 外部 critical/high 盲区总数
```

- `expected_gaps` 来自 `core_knowledge_map.json` 与测试用例，不读取模型自报盲区。
- 只认可资源标题/正文实际出现的主题或别名。
- `target_skill_gaps` 只是生成计划，不是覆盖证据。
- 无 `critical/high` 盲区时标为不可评估，不自动通过。

## 5. 测试集结构

当前构造为：

```text
3 个外部画像 × 18 个 core/high 知识点 = 54 个正向用例
+ 4 个负向用例
= 58 个用例
```

4 个负样本分别验证：未知 FANUC 报警码、危险安全旁路请求、知识库外厂商隐藏指令、诱导系统忽略画像。负样本与三项正向指标分开报告，避免通过“故意失败”污染正常指标分母。

测试用例文件只包含输入、外部真值和预期行为，明确声明：

```json
{
  "contains_model_outputs": false,
  "contains_measured_metrics": false
}
```

## 6. 完整复现流程

所有命令在仓库根目录执行。

### 6.1 重建并校验输入真值

```powershell
python scripts/build_phase3_dataset.py
python scripts/validate_phase3_dataset.py --dataset-only
```

第一条命令确定性重建 58 个用例；第二条校验画像、核心知识点、来源文件、笛卡尔积和 3–5 个负样本，但暂不要求人工 gold 完成。

### 6.2 采集真实流水线输出

先按项目 README 启动后端，再执行：

```powershell
python scripts/collect_phase3_outputs.py `
  --output data/evaluation/runs/phase3_raw_outputs.json
```

采集脚本只保存 `/api/generate` 原始响应，不打分、不改写响应。后端是否调用付费 LLM 由 `.env` 决定；运行前必须确认当前为演示模式还是真实模式。脚本默认不覆盖已有文件，需明确加 `--overwrite` 才能覆盖。

### 6.3 首次离线评测并导出待标断言

```powershell
python scripts/run_phase3_evaluation.py `
  --outputs data/evaluation/runs/phase3_raw_outputs.json `
  --output-report data/evaluation/runs/phase3_report.json
```

该脚本不调用 LLM。首次运行若没有 50 条人工金标准，会正常写出报告并以非零状态结束；报告中的 `gold_candidate_claims` 是待人工标注候选，不是金标准。

### 6.4 完成人工 gold 并执行发布门禁

```powershell
Copy-Item data/evaluation/gold_labels.template.json data/evaluation/gold_labels.json
# 按 docs/GOLD_LABELING_GUIDE.md 完成人工双人标注
python scripts/validate_phase3_dataset.py
```

默认校验是发布门禁：少于 50 条完整、双人复核且非 `skip` 的事实标签必定失败。门禁通过后，再运行 6.3 的离线评测生成最终报告。

## 7. 测试与验收

```powershell
python -m pytest backend/tests -q
python -m ruff check backend scripts
```

最终测试报告至少记录：代码版本、知识库版本、画像与测试集版本、模型/演示模式、原始输出文件、三项聚合指标、负样本结果、Agent3 人工标定准确率、失败用例和修复结论。只有三项指标、全部负样本和人工标定同时通过时，`run_phase3_evaluation.py` 才输出 `release_ready=true`。

## 8. 接口兼容说明

- 根目录 `main.py` 与 `backend/src/api/main.py` 都注册前置测试和画像路由。
- 新接口为增量添加，不修改 `/api/generate`。
- `FactCheckItem.verdict` 使用 `accurate | hallucination | unverifiable | skip`；旧的 `is_accurate` 仅保留为兼容字段，不能表达完整三态合同。
- 接口字段的单一模型定义仍位于 `backend/src/schemas.py`。
