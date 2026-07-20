"""
方案 B — 暗色主题
启动: streamlit run frontend/streamlit/app_v2.py --server.port 8502
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend" / "src"))

import streamlit as st
import requests

st.set_page_config(
    page_title="领域知识个性化生成系统",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def theme_css() -> str:
    return """<style>
:root {
    --bg:         #0b0d10;
    --card:       #16181b;
    --border:     #272a2f;
    --border-focus: #3b82f6;
    --text:       #e4e4e8;
    --text2:      #9ca3af;
    --text3:      #6b7280;
    --accent:     #3b82f6;
    --tag-bg:     #1e293b;
    --code-bg:    #1e1e1e;
    --radius:     6px;
}
* { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif; }

html, body { background: var(--bg) !important; }
.stApp, .stMain, .main, .stApp > div { background: var(--bg) !important; }
.main .block-container { padding: 2rem 2.5rem 1.5rem 2.5rem; max-width: 1100px; }

.page-title { margin-bottom: 2rem; }
.page-title h1 { font-size: 1.45rem; font-weight: 600; letter-spacing: -0.02em; color: var(--text); margin: 0; }
.page-title p { font-size: 0.84rem; color: var(--text3); margin-top: 0.1rem; }

/* metric */
[data-testid="stMetric"] {
    background: var(--card) !important; border-radius: 8px !important;
    padding: 1rem 1.2rem !important; border: 1px solid var(--border) !important;
    box-shadow: none !important; margin-bottom: 0.5rem !important;
}
[data-testid="stMetric"] label {
    font-size: 0.7rem !important; font-weight: 500 !important;
    text-transform: none !important; letter-spacing: 0 !important;
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-weight: 620 !important; letter-spacing: -0.02em !important;
    font-size: 1.55rem !important;
}

/* expander */
section[data-testid="stExpander"] {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important; margin-bottom: 0.4rem !important;
    box-shadow: none !important; padding: 0 !important;
    transition: border-color 0.15s ease !important;
}
section[data-testid="stExpander"]:hover { border-color: #3b3f46 !important; }
section[data-testid="stExpander"] details { border-radius: 8px !important; }
section[data-testid="stExpander"] summary {
    font-weight: 500 !important; font-size: 0.88rem !important;
    padding: 0.6rem 0.9rem !important; border-radius: 8px !important;
}
section[data-testid="stExpander"] summary + div {
    padding: 0 0.9rem 0.9rem 0.9rem !important; border-radius: 0 0 8px 8px !important;
}

/* progress */
.stProgress > div > div { height: 5px; border-radius: 3px; background: var(--border) !important; }

/* tabs */
[data-testid="stTabs"] [role="tablist"] { gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 1.5rem; }
.stTabs [role="tab"] {
    font-size: 0.85rem !important; font-weight: 460 !important;
    padding: 0.45rem 1.4rem !important;
    border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s;
}
.stTabs [role="tab"][aria-selected="true"] {
    font-weight: 560 !important; border-bottom-color: var(--accent) !important;
}

.stButton > button { border-radius: var(--radius) !important; font-weight: 500 !important;
    box-shadow: none !important; transition: opacity 0.15s !important; }
.stButton > button:hover { opacity: 0.9; }

/* 总结 */
.summary-box { background: var(--card); padding: 1.2rem 1.5rem;
    border: 1px solid var(--border); border-left: 3px solid var(--accent);
    border-radius: 4px; margin: 1rem 0 1.5rem 0; }
.summary-box .sl { font-size: 0.68rem; font-weight: 500; color: var(--text3); margin-bottom: 0.35rem; }
.summary-box .st { line-height: 1.7; color: var(--text2); font-size: 0.93rem; }

/* 代码块 */
pre, code, .stCodeBlock, [data-testid="stCodeBlock"] {
    background: var(--code-bg) !important; border-radius: 6px !important;
    padding: 0.8rem 1rem !important; font-family: "SF Mono", "Fira Code", Menlo, monospace !important;
    font-size: 0.84rem !important; color: #e4e4e7 !important;
}
code { padding: 0.15rem 0.4rem !important; border-radius: 4px !important; }
pre code { background: transparent !important; padding: 0 !important; }

/* ── 侧边栏 ── */
[data-testid="stSidebar"] {
    background: var(--card) !important; border-right: 1px solid var(--border) !important;
    overflow-y: auto !important; overflow-x: hidden !important;
}
[data-testid="stSidebar"] > div:first-child { overflow: visible !important; }
/* 侧边栏内容区允许子元素溢出（multiselect 下拉需要） */
[data-testid="stSidebar"] .block-container {
    padding: 1.2rem 1rem !important;
    overflow: visible !important;
}
[data-testid="stSidebar"] h3,[data-testid="stSidebar"] h4,[data-testid="stSidebar"] h5 {
    font-weight: 600 !important; margin-top: 1rem !important; margin-bottom: 0.4rem !important;
}
[data-testid="stSidebar"] h4:first-of-type { margin-top: 0 !important; }
[data-testid="stSidebar"] label { font-weight: 500 !important; font-size: 0.82rem !important; margin-bottom: 0.3rem !important; display: block !important; }
/* checkbox 文字跟框同行 */
[data-testid="stSidebar"] .stCheckbox label {
    display: inline-flex !important; align-items: center !important;
    font-size: 0.8rem !important; padding-left: 0.3rem !important; gap: 0.4rem !important;
}
[data-testid="stSidebar"] .stCheckbox label span { display: inline !important; }
/* 确保 checkbox 容器不换行 */
[data-testid="stSidebar"] .stCheckbox > div { display: flex !important; align-items: center !important; }
/* 每个表单元素之间加间距 */
[data-testid="stSidebar"] .stTextInput,
[data-testid="stSidebar"] .stTextArea,
[data-testid="stSidebar"] .stSelectbox,
[data-testid="stSidebar"] .stMultiSelect,
[data-testid="stSidebar"] .stSlider,
[data-testid="stSidebar"] .stCheckbox { margin-bottom: 0.75rem !important; }
/* multiselect 标签和输入区分开 */
[data-testid="stSidebar"] .stMultiSelect [data-testid="stWidgetLabel"] {
    margin-bottom: 0.35rem !important;
}
/* Multiselect 容器确保不溢出 */
[data-testid="stSidebar"] [data-baseweb="select"] {
    min-height: 38px !important;
}
[data-testid="stSidebar"] hr { border-color: var(--border) !important; margin: 0.8rem 0 !important; }

[data-testid="stSidebar"] .stButton > button {
    background: var(--accent) !important; color: #ffffff !important;
    border: none !important; font-weight: 520 !important; border-radius: var(--radius) !important; font-size: 0.88rem !important;
}
[data-testid="stSidebar"] .stButton > button:hover { opacity: 0.9; }

/* 输入框 */
[data-testid="stSidebar"] input,[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    border-radius: var(--radius) !important; background: var(--bg) !important;
    border: 1px solid var(--border) !important; font-size: 0.84rem !important;
}
[data-testid="stSidebar"] input:focus,[data-testid="stSidebar"] textarea:focus {
    border-color: var(--border-focus) !important; box-shadow: 0 0 0 2px rgba(59,130,246,0.15) !important;
}

/* 下拉菜单 */
[data-testid="stSidebar"] [data-baseweb="popover"],
[data-testid="stSidebar"] [role="listbox"] {
    background: var(--card) !important;
    border: 1px solid var(--border) !important; border-radius: var(--radius) !important;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3) !important;
}
[data-testid="stSidebar"] [role="option"]:hover { background: #1f2228 !important; }

/* multiselect — 防止输入框和文字重合 */
[data-testid="stSidebar"] .stMultiSelect {
    overflow: visible !important;
    margin-top: 0.5rem !important;
}
[data-testid="stSidebar"] .stMultiSelect > div {
    flex-wrap: wrap !important; gap: 4px !important;
    padding: 4px !important;
}
[data-testid="stSidebar"] .stMultiSelect > div > div:first-child {
    flex-wrap: wrap !important; gap: 3px !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] {
    z-index: auto !important; overflow: visible !important;
}
[data-testid="stSidebar"] [data-baseweb="popover"] { z-index: 999999 !important; }
[data-testid="stSidebar"] [data-baseweb="tag"] {
    border-radius: 4px !important; padding: 2px 8px !important; margin: 2px !important;
    background: var(--tag-bg) !important; border: none !important; white-space: nowrap !important;
}
/* 输入区跟标签行之间有间距 */
[data-testid="stSidebar"] [data-baseweb="stMultiSelect"] [data-baseweb="input"] {
    margin-left: 2px !important; min-width: 60px !important;
}

/* slider */
.stSlider [role="slider"] { height: 16px !important; width: 16px !important; }
.stSlider > div > div > div { height: 4px !important; border-radius: 2px !important; background: var(--border) !important; }

[data-testid="stSidebar"] .stCheckbox label { font-size: 0.8rem !important; }
hr,.stDivider { border-color: var(--border) !important; margin: 1.2rem 0 !important; }
</style>"""


st.markdown(theme_css(), unsafe_allow_html=True)

# ═══ 数据 ═══
API_BASE = "http://localhost:8000"

FAKE_RESULT = {
    "status": "completed",
    "diagnosis": {
        "knowledge_map": {
            "Python 编程": {"level": 0.70, "confidence": 0.90},
            "LLM 基础": {"level": 0.40, "confidence": 0.70},
            "LangGraph": {"level": 0.10, "confidence": 0.80},
            "RAG 检索": {"level": 0.20, "confidence": 0.60},
            "Agent 架构": {"level": 0.10, "confidence": 0.80},
        },
        "skill_gaps": [
            {"topic": "LangGraph 状态图", "current_level": 0.10, "target_level": 0.80,
             "priority": "critical", "reason": "LangGraph 核心概念，不掌握无法推进"},
            {"topic": "Agent 通信模式", "current_level": 0.10, "target_level": 0.80,
             "priority": "critical", "reason": "协同系统需要理解 Agent 间通信"},
            {"topic": "RAG 检索流程", "current_level": 0.20, "target_level": 0.70,
             "priority": "high", "reason": "知识生成依赖 RAG，前置依赖"},
            {"topic": "Prompt Engineering", "current_level": 0.30, "target_level": 0.70,
             "priority": "high", "reason": "多 Agent 系统需要精心设计 prompt"},
            {"topic": "向量数据库", "current_level": 0.20, "target_level": 0.60,
             "priority": "medium", "reason": "RAG 依赖向量检索，可后续学习"},
        ],
        "learning_style": "practice_first",
        "recommended_difficulty": "beginner",
        "summary": "该学习者有计算机专业背景和 Python 开发经验，编程基础扎实。但对 LLM 应用开发领域的系统性知识较为薄弱，特别是 LangGraph、RAG 和 Agent 架构。建议从实操项目入手，边做边学。",
    },
    "resources": [
        {
            "resource_type": "lecture", "title": "LangGraph 入门讲义",
            "content": """## 什么是 LangGraph

LangGraph 是 LangChain 团队推出的库，用于构建有状态的多步骤 LLM 应用。

### 核心概念

`StateGraph` 用状态字典在多个节点间传递数据。

```python
from langgraph.graph import StateGraph, END

workflow = StateGraph(dict)

def node_a(state):
    return {"result": "A 完成"}

workflow.add_node("a", node_a)
workflow.set_entry_point("a")
workflow.add_edge("a", END)

app = workflow.compile()
app.invoke({})
```

### 为什么多 Agent

- 关注点分离：每个 Agent 各司其职
- 可维护：修改互不影响
- 可扩展：新能力即新 Agent

### 学习路径

1. StateGraph 基本用法
2. 节点和边的原理
3. 条件路由
4. 2-Agent 协同
5. 复杂架构扩展""",
            "difficulty_level": "beginner", "estimated_duration_minutes": 30,
            "key_takeaways": ["StateGraph 状态管理", "三要素：节点、边、字典", "关注点分离"],
        },
        {
            "resource_type": "guide", "title": "构建第一个 LangGraph 应用",
            "content": """## 步骤一：安装

```bash
pip install langgraph langchain-openai
```

## 步骤二：定义 StateGraph

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class MyState(TypedDict):
    query: str
    result: str

def analyze(state: MyState) -> dict:
    return {"result": f"已分析: {state['query']}"}

workflow = StateGraph(MyState)
workflow.add_node("analyze", analyze)
workflow.set_entry_point("analyze")
workflow.add_edge("analyze", END)
app = workflow.compile()
```

## 步骤三：运行

```python
result = app.invoke({"query": "学习 LangGraph", "result": ""})
print(result["result"])
```

## 步骤四：条件路由

```python
def router(state: MyState) -> str:
    if "LangGraph" in state["query"]:
        return "langgraph_node"
    return "general_node"

workflow.add_conditional_edges(
    "analyze", router,
    {"langgraph_node": "specialized", "general_node": END}
)
```""",
            "difficulty_level": "beginner", "estimated_duration_minutes": 20,
            "key_takeaways": ["三步：State → 节点 → 编译", "条件路由 = 多 Agent 关键", "代码直接可用"],
        },
        {
            "resource_type": "quiz", "title": "LangGraph 基础测试",
            "content": """## 基础题

**1. LangGraph 最核心的抽象是什么？**
- A) Chain
- B) StateGraph ✓
- C) AgentExecutor
- D) Pipeline

**2. 以下哪个不属于 StateGraph 的要素？**
- A) 节点
- B) 边
- C) 模型训练 ✓
- D) 状态字典

**3. 条件路由的作用是？**
- A) 加速推理
- B) 根据中间结果选择下一节点 ✓
- C) 减少 token
- D) 缓存

## 进阶题

**4. 多 Agent 架构相比单体 LLM 调用的核心优势是什么？**

## 挑战题

**5. 设计工作流：输入 → 判断类型 → GPT-4 / GPT-3.5 → 输出结果。**""",
            "difficulty_level": "beginner", "estimated_duration_minutes": 15,
            "key_takeaways": ["检验 StateGraph 概念理解", "逐级递进评估"],
        },
    ],
    "audit": [
        {"resource_index": 0, "resource_type": "lecture", "verdict": "needs_revision",
         "issues": [{"severity": "warning", "detail": "beginner 水平但跳过了中间过渡概念"},
                    {"severity": "info", "detail": "可增加架构对比图"}]},
        {"resource_index": 1, "resource_type": "guide", "verdict": "approved",
         "issues": [{"severity": "info", "detail": "conditional_edges 可补充完整的 specialized 节点实现"}]},
        {"resource_index": 2, "resource_type": "quiz", "verdict": "approved", "issues": []},
    ],
    "agent_log": [
        {"agent": "diagnosis", "status": "done"},
        {"agent": "generation", "status": "done", "count": 3},
        {"agent": "audit", "status": "done"},
    ],
}


def call_backend(data: dict) -> dict | None:
    try:
        r = requests.post(f"{API_BASE}/api/generate", json=data, timeout=120)
        if r.status_code == 200: return r.json()
        st.error(f"API ({r.status_code})")
    except requests.exceptions.ConnectionError:
        st.warning("后端未启动，请执行: python -m uvicorn src.api.main:app --port 8000")
    except Exception as e:
        st.error(f"请求失败: {e}")
    return None


_LS = {"practice_first": "实践优先", "theory_first": "理论优先", "visual": "视觉学习", "project_based": "项目驱动"}
_DF = {"beginner": "入门", "intermediate": "进阶", "advanced": "高级"}
_PR = {"critical": "紧急", "high": "重要", "medium": "一般", "low": "可选"}
_ICN = {"lecture": "📖", "guide": "🛠️", "quiz": "✏️"}
_AGT = {"diagnosis": "学情诊断 Agent", "generation": "知识生成 Agent", "audit": "审核裁判 Agent"}
_STAT = {"starting": "准备中", "diagnosing": "学情诊断中", "generating": "知识生成中", "auditing": "审核裁判中", "completed": "全部完成"}


def show_diagnosis(diag: dict) -> None:
    style = diag.get("learning_style", "")
    diff = diag.get("recommended_difficulty", "")
    gaps = diag.get("skill_gaps", [])

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        st.metric("学习风格", _LS.get(style, style))
        st.caption("根据学历、经历、测试结果综合推断")
    with c2:
        st.metric("推荐难度", _DF.get(diff, diff))
        st.caption("匹配当前知识水平的初始难度")
    with c3:
        st.metric("知识盲区", f"{len(gaps)} 项")
        st.caption("需要优先填补的关键知识点")

    summary = diag.get("summary", "")
    if summary:
        st.markdown(f"""
        <div class="summary-box">
            <div class="sl">整体画像</div>
            <div class="st">{summary}</div>
        </div>
        """, unsafe_allow_html=True)

    st.caption("知识盲区")
    if gaps:
        for g in gaps:
            p = g.get("priority", "medium")
            lb = _PR.get(p, p)
            label = f"{lb}  {g.get('topic', '?')} — {g.get('current_level',0):.0%} → {g.get('target_level',1):.0%}"
            with st.expander(label):
                st.write(g.get("reason", ""))
    else:
        st.info("未发现明显盲区")

    st.caption("知识掌握度")
    km = diag.get("knowledge_map", {})
    if km:
        for topic, info in km.items():
            lv = info.get("level", 0) if isinstance(info, dict) else 0
            cf = info.get("confidence", 0) if isinstance(info, dict) else 0
            st.write(f"**{topic}**")
            a, b, c = st.columns([5, 0.8, 1])
            with a: st.progress(lv)
            with b: st.caption(f"{lv:.0%}")
            with c: st.caption(f"置信度 {cf:.0%}")
    else:
        st.info("暂无数据")


def show_resources(resources: list, audit_list: list) -> None:
    ab = {}
    for a in (audit_list or []):
        ab[a.get("resource_index", -1)] = a

    TP = {"lecture": "讲义", "guide": "指南", "quiz": "测试"}
    VD = {"approved": "通过", "needs_revision": "需修改", "rejected": "不通过"}

    if not resources:
        st.info("无生成资源")
        return

    for i, res in enumerate(resources):
        rt = res.get("resource_type", "lecture")
        icon = _ICN.get(rt, "📄")
        ae = ab.get(i)
        if ae:
            v = ae.get("verdict", "")
            v_tag = f" — {VD.get(v, v)}"
        else:
            v_tag = ""
        title = f"{icon}  {TP.get(rt, rt)} · {res.get('title', f'资源 {i+1}')}{v_tag}"

        with st.expander(title, expanded=(i == 0)):
            if ae:
                for iss in ae.get("issues", []):
                    s = iss.get("severity", "info")
                    if s == "error":   st.error(iss.get("detail", ""))
                    elif s == "warning": st.warning(iss.get("detail", ""))
                    else:              st.info(iss.get("detail", ""))

            content = res.get("content", "")
            if content: st.markdown(content)
            else:       st.info("暂无内容")

            dur = res.get("estimated_duration_minutes")
            if dur: st.caption(f"预计 {dur} 分钟")
            if res.get("key_takeaways"):
                st.caption(" · ".join(res["key_takeaways"]))


def show_audit(audit_list: list) -> None:
    if not audit_list:
        st.info("无审核数据")
        return

    n = len(audit_list)
    ok = sum(1 for a in audit_list if a.get("verdict") == "approved")
    wn = sum(1 for a in audit_list if a.get("verdict") == "needs_revision")
    bd = sum(1 for a in audit_list if a.get("verdict") == "rejected")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("资源总数", f"{n}")
        st.caption("已生成的学习资源")
    with c2:
        st.metric("通过", f"✓ {ok}")
        st.caption("无需修改，可直接使用")
    with c3:
        st.metric("需修改", f"! {wn}")
        st.caption("有小问题需要调整")
    with c4:
        st.metric("不通过", f"✕ {bd}")
        st.caption("存在事实错误需重做")

    TC = {"lecture": "讲义", "guide": "指南", "quiz": "测试"}
    for a in audit_list:
        idx = a.get("resource_index", "?")
        rt = a.get("resource_type", "?")
        v = a.get("verdict", "")
        lb = {"approved": "通过", "needs_revision": "需修改", "rejected": "不通过"}.get(v, v)
        title = f"{lb}  资源 #{idx}（{TC.get(rt, rt)}）"
        with st.expander(title):
            for iss in a.get("issues", []):
                s = iss.get("severity", "info")
                if s == "error":   st.error(iss.get("detail", ""))
                elif s == "warning": st.warning(iss.get("detail", ""))
                else:              st.info(iss.get("detail", ""))
            if not a.get("issues"):
                st.success("无问题，审核通过")


# ═══ 页面 ═══

st.markdown("""
<div class="page-title">
    <h1>领域知识个性化生成系统</h1>
    <p>学情诊断 · 知识生成 · 审核裁判</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("#### 学习目标")
    learning_goal = st.text_area(
        "学习目标", "学习使用 LangGraph 构建多智能体 AI 应用",
        height=80, placeholder="你想学什么？",
    )

    st.markdown("#### 基本信息")
    ca, cb = st.columns(2)
    with ca:
        education_level = st.selectbox(
            "学历", ["high_school", "junior_college", "bachelor", "master", "phd"], index=2,
            format_func=lambda x: {"high_school": "高中","junior_college":"大专","bachelor":"本科","master":"硕士","phd":"博士"}[x],
        )
    with cb:
        major = st.text_input("专业", "计算机科学")
    skills_used = st.text_input("已掌握技能", "Python, Flask, SQL", placeholder="逗号分隔")

    st.markdown("#### 工作背景")
    cc, cd = st.columns(2)
    with cc:
        work_years = st.slider("工作年限", 0.0, 20.0, 1.0, 0.5)
    with cd:
        industry = st.text_input("所在行业", "互联网")
    positions = st.text_input("岗位", "Python 开发", placeholder="逗号分隔")

    st.markdown("#### 输出设置")
    resource_types = st.pills(
        "资源类型",
        options=["定制讲义", "实操指南", "分阶测试"],
        default=["定制讲义", "实操指南", "分阶测试"],
        selection_mode="multi",
    )
    type_map = {"定制讲义": "lecture", "实操指南": "guide", "分阶测试": "quiz"}
    resource_types = [type_map[x] for x in (resource_types or [])]

    st.divider()
    use_fake = st.toggle("使用演示数据", value=False)
    generate_btn = st.button("生成个性化学习资源", type="primary", use_container_width=True)

if generate_btn:
    if use_fake:
        st.session_state.result = FAKE_RESULT
        st.toast("已加载演示数据", icon="✅")
    elif not resource_types:
        st.error("请至少选择一种资源类型")
    elif not learning_goal.strip():
        st.error("请填写学习目标")
    else:
        payload = {
            "learning_goal": learning_goal.strip(),
            "education_level": education_level,
            "major": major.strip(),
            "skills_used": [s.strip() for s in skills_used.split(",") if s.strip()],
            "work_years": float(work_years),
            "industry": industry.strip(),
            "positions": [p.strip() for p in positions.split(",") if p.strip()],
            "pretest_results": [],
            "resource_types": resource_types,
        }
        with st.spinner("多智能体协同工作中..."):
            real = call_backend(payload)
            if real:
                st.session_state.result = real
                st.toast(f"生成完成", icon="✅")
            else:
                st.session_state.result = FAKE_RESULT
                st.toast("后端未就绪，已切换到演示数据", icon="💡")

if "result" in st.session_state and st.session_state.result:
    r = st.session_state.result
    agent_log = r.get("agent_log", [])
    status = r.get("status", "")
    if agent_log:
        cols = st.columns(3)
        for i, (key, name) in enumerate(_AGT.items()):
            le = next((e for e in agent_log if e.get("agent") == key), None)
            done = le is not None
            with cols[i]:
                if done:
                    cnt = le.get("count", "")
                    ex = f"（{cnt} 份）" if cnt else ""
                    st.success(f"✓ {name} 已完成 {ex}", icon="✅")
                else:
                    st.info(f"{name} 等待中")
    st.caption(f"工作流状态：{_STAT.get(status, status)}")

    t1, t2, t3 = st.tabs(["学情诊断", "学习资源", "审核意见"])
    with t1: show_diagnosis(r.get("diagnosis", {}))
    with t2: show_resources(r.get("resources", []), r.get("audit", []))
    with t3: show_audit(r.get("audit", []))
    with st.expander("调试信息", expanded=False):
        st.json(r)
else:
    st.info("在左侧填写学习者信息，点击「生成个性化学习资源」开始")

st.divider()
try:
    h = requests.get(f"{API_BASE}/health", timeout=2).json()
    demo = h.get("demo_mode", True)
    st.caption(f"后端运行中 | {'演示模式' if demo else '真实 API'} | LLM: {h.get('llm','N/A')}")
except Exception:
    st.caption("后端未连接")
