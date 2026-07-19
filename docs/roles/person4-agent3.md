# 人4：Agent 3 — 内容审核

## 你要做什么

文件：`agents/audit.py`

继承人1 的 `BaseAgent`。拿人3 生成的资源 + 人2 的诊断，逐条检查。**只审不修。**

## 输入

`state["generated_resources"]` + `state["diagnosis_result"]`

## 输出

`state["audit_result"]` — 每份资源一条审核意见

```python
[
    {
        "resource_index": 0,
        "resource_type": "lecture",
        "verdict": "approved",
        "issues": []
    },
    {
        "resource_index": 1,
        "resource_type": "guide",
        "verdict": "needs_revision",
        "issues": [
            {"severity": "error", "detail": "API参数名错误"},
            {"severity": "warning", "detail": "难度偏高"}
        ]
    }
]
```

| severity | 含义 |
|----------|------|
| `error` | 事实错误，比如 API 名称写错了 |
| `warning` | 不够好但没错，比如难度偏高、遗漏盲区 |
| `info` | 建议，比如可以加一道题 |

## 检查什么

1. 事实错误：有没有编造不存在的 API、概念定义对不对
2. 难度匹配：给 beginner 的内容不要太难
3. 盲区覆盖：critical 和 high 的盲区有没有被提到

## 你怎么测

- 塞一份有错的资源（比如"LangGraph 是 Google 开发的"）→ Agent 3 应该标出 error
- 塞一份正确的内容 → verdict 为 approved，issues 为空
