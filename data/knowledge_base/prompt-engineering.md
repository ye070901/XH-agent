# Prompt Engineering 实践指南

Prompt Engineering 是一门通过设计输入提示词来控制 LLM 输出质量的工程方法。

## 基础原则

### 1. 清晰、具体、有结构

差的 prompt：
```
"给我讲一下 AI Agent"
```

好的 prompt：
```
"你是一个 AI 教育专家。请用 200-300 字解释什么是 AI Agent，
包括以下要点：
1. AI Agent 的定义
2. AI Agent 和传统程序的三个核心区别
3. 一个简单的代码示例
面向读者：有 2 年 Python 经验的后端工程师"
```

### 2. 角色设定（Persona）

给 LLM 设定一个明确的角色，可以显著提高输出质量。

```
"你是一个严格的代码审查专家。请审查以下 Python 代码，
检查：1) 安全问题 2) 性能问题 3) 可读性问题"
```

### 3. 结构化输出（Structured Output）

要求 JSON 格式输出，便于程序解析：

```
"请按照以下 JSON 格式输出：
{
    'title': str,
    'content': str,
    'difficulty': 'beginner' | 'intermediate' | 'advanced',
    'key_points': list[str]
}"
```

### 4. 提供示例（Few-shot Prompting）

```
"将以下句子翻译成英文：

中文：'今天天气真好'
英文：'The weather is really nice today'

中文：'我想学编程'
英文：'I want to learn programming'

中文：'你好世界'
英文："
```

### 5. 思维链（Chain of Thought）

对于复杂推理任务，让 LLM 一步步思考：

```
"请解答：一个农场有鸡和兔子共 35 只，脚共 94 只。有多少只鸡？

请按步骤思考：
1. 设鸡的数量为 x，兔子的数量为 y
2. 列出方程式
3. 解方程
4. 给出最终答案"
```

## 进阶技巧

### 约束生成（Constrained Generation）

```
"你只能基于以下参考资料来回答问题。如果参考资料中没有相关信息，
你必须回答：'抱歉，提供的参考资料中没有相关信息。' 不要编造信息。"
```

### 自洽性（Self-Consistency）

对同一个问题生成多个回答，投票选出最一致的答案。这对于有确定性答案的问题特别有效。

### 多轮优化

```
Prompt v1: 让 LLM 生成内容
→ 人工评估
→ Prompt v2: 在 v1 的基础上添加约束
→ 对比效果
→ Prompt v3
...
```

## 常见陷阱

1. **过度设计 prompt：** prompt 太复杂反而降低质量。简洁 > 冗长
2. **温度参数不当：** 事实性任务用低温（0.1-0.3），创意任务用高温（0.7-1.0）
3. **忽视 system prompt：** system prompt 比 user prompt 对模型行为影响更大
4. **不测试边界情况：** 多样化的测试用例比大量单一测试更重要
