"""Streamlit 前端 — MVP 版本

启动方式: streamlit run frontend/streamlit/app.py
"""

import sys
from pathlib import Path

# 添加 backend/src 到 Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend" / "src"))

import requests
import streamlit as st

st.set_page_config(
    page_title="多智能体协同决策系统 MVP",
    page_icon="🤖",
    layout="wide",
)

# ── 配置 ──
API_BASE = "http://localhost:8000"

# ── 标题 ──
st.title("🤖 领域知识个性化生成系统")
st.caption("多智能体协同决策 — MVP 版本 (Agent 1: 学情诊断 + Agent 2: 知识生成)")

# ── 侧边栏：学习者信息 ──
with st.sidebar:
    st.header("📋 学习者信息")

    name = st.text_input("姓名", "张三")
    education_level = st.selectbox(
        "学历",
        ["high_school", "junior_college", "bachelor", "master", "phd"],
        index=2,
        format_func=lambda x: {
            "high_school": "高中",
            "junior_college": "大专",
            "bachelor": "本科",
            "master": "硕士",
            "phd": "博士",
        }[x],
    )
    major = st.text_input("专业", "计算机科学")
    work_years = st.slider("工作年限", 0.0, 20.0, 1.0, 0.5)
    industry = st.text_input("行业", "互联网")
    positions = st.text_input("岗位（逗号分隔）", "Python开发")
    skills_used = st.text_input("技能（逗号分隔）", "Python, Flask, SQL")

    st.divider()
    learning_goal = st.text_area(
        "学习目标",
        "学习使用 LangGraph 构建多智能体 AI 应用",
        height=80,
    )

    resource_types = st.multiselect(
        "资源类型",
        ["lecture", "guide", "quiz"],
        default=["lecture", "guide", "quiz"],
        format_func=lambda x: {
            "lecture": "定制讲义",
            "guide": "实操指南",
            "quiz": "分阶测试题",
        }[x],
    )

    generate_btn = st.button("🚀 生成个性化学习资源", type="primary", use_container_width=True)

# ── 主区域 ──
tab1, tab2, tab3 = st.tabs(["📊 学情诊断", "📚 学习资源", "📋 调试信息"])

# ── 生成逻辑 ──
if generate_btn:
    request_data = {
        "name": name,
        "education_level": education_level,
        "major": major,
        "work_years": work_years,
        "industry": industry,
        "positions": [p.strip() for p in positions.split(",") if p.strip()],
        "skills_used": [s.strip() for s in skills_used.split(",") if s.strip()],
        "pretest_results": [],
        "learning_goal": learning_goal,
        "resource_types": resource_types,
    }

    with st.spinner("🤔 Agent 1 (学情诊断) 正在分析你的知识结构..."):
        try:
            response = requests.post(
                f"{API_BASE}/api/generate",
                json=request_data,
                timeout=120,
            )
            if response.status_code == 200:
                result = response.json()
                st.session_state.result = result
                st.success(f"✅ 生成完成！状态: {result.get('status', '')}")
            else:
                st.error(f"❌ API 返回错误: {response.status_code}\n{response.text}")
                st.session_state.result = None
        except requests.exceptions.ConnectionError:
            st.error(
                "❌ 无法连接到后端。请先启动后端: `python -m uvicorn src.api.main:app --port 8000`"
            )
            st.session_state.result = None
        except Exception as e:
            st.error(f"❌ 请求失败: {e}")
            st.session_state.result = None

# ── 显示结果 ──
if "result" in st.session_state and st.session_state.result:
    result = st.session_state.result

    with tab1:
        st.header("📊 学情诊断报告")
        diagnosis = result.get("diagnosis", {})

        if diagnosis:
            # 概览
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("学习风格", diagnosis.get("learning_style", "N/A"))
            with col2:
                st.metric("推荐难度", diagnosis.get("recommended_difficulty", "N/A"))
            with col3:
                gaps = diagnosis.get("skill_gaps", [])
                st.metric("知识盲区数", len(gaps))

            st.subheader("📝 整体画像")
            st.write(diagnosis.get("summary", ""))

            # 知识盲区
            st.subheader("🎯 知识盲区（按优先级）")
            for gap in diagnosis.get("skill_gaps", []):
                priority = gap.get("priority", "?")
                icon = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                }.get(priority, "⚪")
                with st.expander(
                    f"{icon} [{priority.upper()}] {gap.get('topic', '未知')} (当前 {gap.get('current_level', 0):.1f} → 目标 {gap.get('target_level', 1.0):.1f})"
                ):
                    st.write(f"**原因:** {gap.get('reason', '')}")

            # 知识地图
            st.subheader("🗺️ 知识掌握度")
            knowledge_map = diagnosis.get("knowledge_map", {})
            if knowledge_map:
                for topic, info in knowledge_map.items():
                    level = info.get("level", 0) if isinstance(info, dict) else 0
                    confidence = info.get("confidence", 0) if isinstance(info, dict) else 0
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.progress(level, text=f"{topic}: {level:.0%}")
                    with col2:
                        st.caption(f"置信度 {confidence:.0%}")
        else:
            st.info("无诊断结果")

    with tab2:
        st.header("📚 个性化学习资源")
        resources = result.get("resources", [])

        if resources:
            for i, res in enumerate(resources):
                rtype = res.get("resource_type", "lecture")
                icon_map = {"lecture": "📖", "guide": "🛠️", "quiz": "✏️"}
                icon = icon_map.get(rtype, "📄")

                with st.expander(
                    f"{icon} {res.get('title', f'资源 {i + 1}')} — {rtype}",
                    expanded=(i == 0),
                ):
                    content = res.get("content", "")
                    if content:
                        st.markdown(content)
                    else:
                        st.info("无内容")

                    # Citations
                    citations = res.get("citations", [])
                    if citations:
                        st.divider()
                        st.caption(f"📎 引用来源 ({len(citations)} 条)")
                        for c in citations:
                            st.caption(
                                f"> [{c.get('ref_index', '?')}] {c.get('original_text', '')[:200]}"
                            )
        else:
            st.info("无生成资源")

    with tab3:
        st.header("📋 Agent 执行日志")
        st.json(result.get("agent_log", []))
        st.divider()
        st.header("📋 原始响应")
        st.json(result)

else:
    # 初始状态
    with tab1:
        st.info("👈 在左侧填写学习者信息，点击「生成个性化学习资源」开始")
    with tab2:
        st.info("👈 生成后这里将显示个性化学习资源")
    with tab3:
        st.info("👈 生成后这里将显示调试信息")

# ── 底部状态 ──
st.divider()
try:
    health = requests.get(f"{API_BASE}/health", timeout=2)
    kb_docs = health.json().get("kb_docs", 0)
    st.caption(f"🟢 后端运行中 | LLM: {health.json().get('llm', 'N/A')} | 知识库文档: {kb_docs} 篇")
except Exception:
    st.caption("🔴 后端未连接 — 请先启动: `python -m uvicorn src.api.main:app --port 8000`")
