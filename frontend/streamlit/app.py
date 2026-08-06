"""Streamlit 前端 — Phase2 工业机器人调试助手

启动方式: streamlit run frontend/streamlit/app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend" / "src"))

import requests
import streamlit as st

st.set_page_config(
    page_title="工业机器人调试助手",
    page_icon="🤖",
    layout="wide",
)

# ── 配置 ──
API_BASE = "http://localhost:8000"

# ── 标题 ──
st.title("🤖 工业机器人调试助手")
st.caption("多智能体协同决策 + RAG — 支持 FANUC / KUKA / ABB")

# ── 侧边栏：问题输入 ──
with st.sidebar:
    st.header("📝 调试问题")

    user_input = st.text_area(
        "输入问题",
        placeholder="例如：FANUC 机器人报 SRVO-068 怎么处理",
        height=150,
    )

    submitted = st.button(
        "🔍 诊断并生成方案",
        type="primary",
        use_container_width=True,
    )

    st.divider()
    st.caption("💡 示例问题：")
    st.caption("- FANUC SRVO-068 故障处理")
    st.caption("- KUKA 工具坐标系标定步骤")
    st.caption("- ABB 机器人关节运动编程")

# ── 主区域 ──
tab1, tab2, tab3, tab4 = st.tabs(
    ["📋 诊断结果", "📊 性能指标", "🔍 引用来源", "📚 知识库管理"]
)

# ── 生成逻辑 ──
if submitted and user_input.strip():
    with st.spinner("🤖 正在诊断问题..."):
        try:
            response = requests.post(
                f"{API_BASE}/api/generate",
                json={"user_input": user_input},
                timeout=300,
            )

            if response.status_code == 200:
                result = response.json()
                st.session_state.result = result
                st.session_state.user_input = user_input
                st.success("✅ 生成完成")
            elif response.status_code == 422:
                st.error("❌ 输入不能为空")
            else:
                st.error(f"❌ API 返回错误: {response.status_code}\n{response.text}")
                st.session_state.result = None

        except requests.exceptions.ConnectionError:
            st.error(
                "❌ 无法连接到后端。请先启动后端:\n"
                "`uvicorn backend.src.api.main:app --port 8000`"
            )
            st.session_state.result = None
        except Exception as e:
            st.error(f"❌ 请求失败: {e}")
            st.session_state.result = None

# ── 显示结果 ──
if "result" in st.session_state and st.session_state.result:
    result = st.session_state.result
    res_data = result.get("result", {})
    metrics = result.get("metrics", {})

    with tab1:
        st.header("📋 诊断结果")
        st.info(f"**问题:** {st.session_state.get('user_input', '')}")

        st.subheader("💡 生成方案")
        answer = res_data.get("answer", "")
        if answer:
            st.markdown(answer)
        else:
            st.warning("未生成相关内容")

        col1, col2 = st.columns(2)
        with col1:
            confidence = res_data.get("confidence", 0)
            st.metric("置信度", f"{confidence:.0%}")
        with col2:
            st.metric(
                "状态",
                result.get("status", "unknown"),
            )

    with tab2:
        st.header("📊 性能指标")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                "输入闸门",
                f"{metrics.get('inputgate_ms', 0)} ms",
            )
        with col2:
            st.metric(
                "诊断闸门",
                f"{metrics.get('diagnosisgate_ms', 0)} ms",
            )
        with col3:
            st.metric(
                "召回闸门",
                f"{metrics.get('recallgate_ms', 0)} ms",
            )

        col4, col5, col6 = st.columns(3)
        with col4:
            st.metric(
                "召回文档数",
                metrics.get("rag_recall_count", 0),
            )
        with col5:
            st.metric("TOP-K", metrics.get("rag_top_k", 5))
        with col6:
            st.metric(
                "总延迟",
                f"{metrics.get('total_latency_ms', 0)} ms",
            )

    with tab3:
        st.header("🔍 引用来源")
        sources = res_data.get("sources", [])
        if sources:
            for i, source in enumerate(sources, 1):
                st.caption(f"{i}. {source}")
        else:
            st.info("无引用来源")

        st.divider()
        st.subheader("原始响应")
        st.json(result)

else:
    # 初始状态
    with tab1:
        st.info("👈 在左侧输入工业机器人调试问题，点击「诊断并生成方案」开始")
    with tab2:
        st.info("👈 生成后这里将显示性能指标")
    with tab3:
        st.info("👈 生成后这里将显示引用来源")

# ── Tab 4: 知识库管理（始终可用，不依赖生成按钮） ──
with tab4:
    st.header("📚 知识库管理")

    kb_col1, kb_col2 = st.columns([2, 1])

    with kb_col1:
        st.subheader("📝 文档导入")

        import_mode = st.radio(
            "导入方式", ["手动粘贴", "批量导入 data/raw/"], horizontal=True
        )

        if import_mode == "手动粘贴":
            with st.form("kb_upload_form"):
                doc_title = st.text_input(
                    "文档标题（技术关键词 + 核心要点）",
                    placeholder="FANUC 示教器点位编程步骤",
                )
                doc_content = st.text_area(
                    "Markdown 正文（500~5000 字）",
                    placeholder="# 标题\n\n- **来源**：https://...\n- **权威等级**：A\n\n## 正文\n\n...",
                    height=300,
                )
                submitted_kb = st.form_submit_button(
                    "📤 上传到知识库", type="primary", use_container_width=True
                )

                if submitted_kb:
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
                                json={
                                    "doc_id": doc_id,
                                    "title": doc_title,
                                    "content": doc_content,
                                },
                                timeout=30,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                st.success(
                                    f"✅ 上传成功！文档 '{doc_title}' → {data['chunks_count']} chunks"
                                )
                                st.rerun()
                            else:
                                st.error(f"上传失败: {resp.status_code} — {resp.text}")
                        except requests.exceptions.ConnectionError:
                            st.error("❌ 无法连接后端，请先启动服务")

        else:
            st.caption("一键导入 data/raw/ 目录下全部 .md 文件")
            if st.button(
                "🔄 批量导入", type="primary", use_container_width=True
            ):
                try:
                    with st.spinner("正在导入..."):
                        resp = requests.post(
                            f"{API_BASE}/api/knowledge/import", timeout=60
                        )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.success(
                            f"✅ 导入完成: {data['imported']}/{data['total']} 篇"
                        )
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
        search_btn = st.button(
            "🔍 检索", use_container_width=True, key="kb_search_btn"
        )

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
        f"🟢 后端运行中 | LLM: {health.json().get('llm', 'N/A')} | "
        f"知识库文档: {kb_docs} 篇 | API: v0.3.0"
    )
except Exception:
    st.caption(
        "🔴 后端未连接 — 请先启动: `uvicorn backend.src.api.main:app --port 8000`"
    )
