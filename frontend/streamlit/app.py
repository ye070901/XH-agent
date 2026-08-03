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

    generate_btn = st.button(
        "🚀 生成个性化学习资源", type="primary", use_container_width=True
    )

# ── 主区域 ──
tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 学情诊断", "📚 学习资源", "📋 调试信息", "📚 知识库管理"]
)

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
                    confidence = (
                        info.get("confidence", 0) if isinstance(info, dict) else 0
                    )
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

# ── Tab 4: 知识库管理（始终可用，不依赖生成按钮） ──
with tab4:
    st.header("📚 知识库管理")

    kb_col1, kb_col2 = st.columns([2, 1])

    with kb_col1:
        st.subheader("📝 文档导入")

        import_mode = st.radio("导入方式", ["手动粘贴", "批量导入 data/raw/"], horizontal=True)

        if import_mode == "手动粘贴":
            with st.form("kb_upload_form"):
                doc_title = st.text_input("文档标题（技术关键词 + 核心要点）", placeholder="FANUC 示教器点位编程步骤")
                doc_content = st.text_area(
                    "Markdown 正文（500~5000 字）",
                    placeholder="# 标题\n\n- **来源**：https://...\n- **权威等级**：A\n\n## 正文\n\n...",
                    height=300,
                )
                submitted = st.form_submit_button("📤 上传到知识库", type="primary", use_container_width=True)

                if submitted:
                    if not doc_title.strip() or not doc_content.strip():
                        st.error("标题和正文均不能为空")
                    elif len(doc_content) < 500:
                        st.warning(f"⚠️ 正文仅 {len(doc_content)} 字，建议 ≥500 字")
                    else:
                        import hashlib
                        doc_id = hashlib.md5(doc_title.encode()).hexdigest()[:12]
                        try:
                            resp = requests.post(
                                f"{API_BASE}/api/knowledge/upload",
                                json={"doc_id": doc_id, "title": doc_title, "content": doc_content},
                                timeout=30,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                st.success(f"✅ 上传成功！文档 '{doc_title}' → {data['chunks_count']} chunks")
                                st.rerun()
                            else:
                                st.error(f"上传失败: {resp.status_code} — {resp.text}")
                        except requests.exceptions.ConnectionError:
                            st.error("❌ 无法连接后端，请先启动服务")

        else:
            st.caption("一键导入 data/raw/ 目录下全部 .md 文件")
            if st.button("🔄 批量导入", type="primary", use_container_width=True):
                try:
                    with st.spinner("正在导入..."):
                        resp = requests.post(f"{API_BASE}/api/knowledge/import", timeout=60)
                    if resp.status_code == 200:
                        data = resp.json()
                        st.success(f"✅ 导入完成: {data['imported']}/{data['total']} 篇")
                        st.rerun()
                    else:
                        st.error(f"导入失败: {resp.status_code}")
                except requests.exceptions.ConnectionError:
                    st.error("❌ 无法连接后端")

    with kb_col2:
        st.subheader("📊 知识库状态")
        try:
            resp = requests.get(f"{API_BASE}/api/knowledge/stats", timeout=5)
            if resp.status_code == 200:
                stats = resp.json()
                st.metric("模式", stats.get("mode", "?"))
                st.metric("文档数", stats.get("total_documents", 0))
                st.metric("Chunk 数", stats.get("total_chunks", 0))
            else:
                st.warning("状态获取失败")
        except Exception:
            st.warning("后端未连接")

    st.divider()
    st.subheader("🔍 知识库检索测试")

    search_col1, search_col2 = st.columns([4, 1])
    with search_col1:
        search_input = st.text_input(
            "输入检索关键词",
            placeholder="例如：FANUC SRVO-068 故障处理、工具坐标系、RobotStudio 仿真",
            key="kb_search_input",
        )
    with search_col2:
        search_btn = st.button("🔍 检索", use_container_width=True, key="kb_search_btn")

    if search_btn and search_input.strip():
        try:
            resp = requests.get(
                f"{API_BASE}/api/knowledge/search",
                params={"q": search_input, "top_k": 5},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    st.success(f"找到 {len(results)} 条相关结果")
                    for i, r in enumerate(results):
                        with st.expander(
                            f"📄 [{r['relevance_score']:.2f}] {r['doc_title']} — {r['doc_id']}"
                        ):
                            st.text_area(
                                f"Chunk {r['chunk_index']}",
                                value=r["content"],
                                height=200,
                                key=f"kb_result_{i}",
                            )
                else:
                    st.info("未找到相关文档")
            else:
                st.error(f"检索失败: {resp.status_code}")
        except requests.exceptions.ConnectionError:
            st.error("❌ 无法连接后端")

# ── 底部状态 ──
st.divider()
try:
    health = requests.get(f"{API_BASE}/health", timeout=2)
    kb_docs = health.json().get("kb_docs", 0)
    st.caption(
        f"🟢 后端运行中 | LLM: {health.json().get('llm', 'N/A')} | 知识库文档: {kb_docs} 篇"
    )
except Exception:
    st.caption(
        "🔴 后端未连接 — 请先启动: `python -m uvicorn src.api.main:app --port 8000`"
    )
