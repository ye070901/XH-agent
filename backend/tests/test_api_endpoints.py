"""API 端点集成测试 — Opt-4 API + 界面验证

覆盖 PHASE2_PLAN.md 2.8 Opt-4 全部 6 个 API 端点：
  - POST /api/generate
  - POST /api/knowledge/upload
  - POST /api/knowledge/import
  - GET  /api/knowledge/search
  - GET  /api/knowledge/stats
  - DELETE /api/knowledge/{doc_id}

使用 FastAPI TestClient 直接测试，不依赖后端服务启动。
"""

from __future__ import annotations

# 必须先设置 sys.path，再导入 app
import sys
from pathlib import Path

root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root / "backend"))

import hashlib  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from backend.src.api.main import app  # noqa: E402

client = TestClient(app)


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def make_doc_id(title: str) -> str:
    """生成与 app_v2.py 一致的 doc_id"""
    return hashlib.md5(title.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════
# 1. GET / — 根路径
# ═══════════════════════════════════════════════════════════

class TestRootEndpoint:
    def test_root_returns_name_and_status(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert data["name"] == "领域知识个性化生成系统"
        assert "status" in data
        assert "version" in data


# ═══════════════════════════════════════════════════════════
# 2. GET /health — 健康检查
# ═══════════════════════════════════════════════════════════

class TestHealthEndpoint:
    def test_health_returns_status(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "llm" in data
        assert "kb_docs" in data
        assert "kb_mode" in data


# ═══════════════════════════════════════════════════════════
# 3. POST /api/generate — 主接口（硬性约束验证）
# ═══════════════════════════════════════════════════════════

class TestGenerateEndpoint:
    """验证 2.9 API 接口硬性约束"""

    def test_generate_empty_input_returns_422(self):
        """约束：入参结构不可变，user_input 为必填"""
        response = client.post("/api/generate", json={})
        assert response.status_code == 422

    def test_generate_empty_string_returns_422(self):
        """约束：user_input 不能为空字符串"""
        response = client.post("/api/generate", json={"user_input": "   "})
        assert response.status_code == 422

    def test_generate_accepted_returns_valid_structure(self):
        """约束：出参结构 {status, result: {answer, sources, confidence}, metrics}"""
        with patch("backend.src.api.main.scheduler.run_pipeline", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "status": "completed",
                "gate_results": {
                    "input_gate": {"duration_ms": 10},
                    "diagnosis_gate": {"duration_ms": 20},
                    "recall_gate": {"duration_ms": 30},
                },
                "retrieved_chunks": [
                    {"doc_id": "test", "doc_title": "Test", "content": "content"}
                ],
                "generated_resources": [
                    {"title": "Resource 1", "content": "Some content"}
                ],
                "elapsed_ms": 100,
            }
            response = client.post(
                "/api/generate",
                json={"user_input": "FANUC SRVO-068 怎么处理"}
            )
            assert response.status_code == 200
            data = response.json()

            # 硬性约束：顶层字段
            assert "status" in data
            assert "result" in data
            assert "metrics" in data

            # 硬性约束：result 结构
            result = data["result"]
            assert "answer" in result
            assert "sources" in result
            assert "confidence" in result
            assert isinstance(result["sources"], list)
            assert isinstance(result["confidence"], float)

            # 硬性约束：metrics 结构
            metrics = data["metrics"]
            assert "inputgate_ms" in metrics
            assert "diagnosisgate_ms" in metrics
            assert "recallgate_ms" in metrics
            assert "rag_recall_count" in metrics
            assert "rag_top_k" in metrics
            assert "total_latency_ms" in metrics

    def test_generate_with_learning_goal_format(self):
        """支持前端 learning_goal 格式"""
        with patch("backend.src.api.main.scheduler.run_pipeline", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "status": "completed",
                "gate_results": {},
                "retrieved_chunks": [],
                "generated_resources": [],
                "elapsed_ms": 50,
            }
            response = client.post(
                "/api/generate",
                json={"learning_goal": "学习 FANUC 机器人编程"}
            )
            assert response.status_code == 200

    def test_generate_exception_returns_500(self):
        """异常处理：500 兜底"""
        with patch(
            "backend.src.api.main.scheduler.run_pipeline",
            new_callable=AsyncMock,
            side_effect=Exception("Test error")
        ):
            response = client.post(
                "/api/generate",
                json={"user_input": "test"}
            )
            assert response.status_code == 500


# ═══════════════════════════════════════════════════════════
# 4. POST /api/knowledge/upload — 单篇上传
# ═══════════════════════════════════════════════════════════

class TestKnowledgeUpload:
    """KB 页面 → KB 引擎单篇入库"""

    def test_upload_missing_doc_id_returns_422(self):
        response = client.post(
            "/api/knowledge/upload",
            json={"title": "Test", "content": "Test content"}
        )
        assert response.status_code == 422
        assert "doc_id" in response.json()["detail"]

    def test_upload_missing_title_returns_422(self):
        response = client.post(
            "/api/knowledge/upload",
            json={"doc_id": "test123", "content": "Test content"}
        )
        assert response.status_code == 422
        assert "title" in response.json()["detail"]

    def test_upload_missing_content_returns_422(self):
        response = client.post(
            "/api/knowledge/upload",
            json={"doc_id": "test123", "title": "Test"}
        )
        assert response.status_code == 422
        assert "content" in response.json()["detail"]

    def test_upload_success_returns_chunks_count(self):
        """成功上传返回 chunks_count"""
        with patch(
            "backend.src.api.main.knowledge_base.add_document",
            new_callable=AsyncMock,
            return_value=[{"chunk_index": 0, "content": "test"}]
        ):
            response = client.post(
                "/api/knowledge/upload",
                json={
                    "doc_id": "test_upload_001",
                    "title": "Test Upload",
                    "content": (
                        "# Test\n\n"
                        "This is test content with enough characters "
                        "to create chunks."
                    ),
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["doc_id"] == "test_upload_001"
            assert "chunks_count" in data


# ═══════════════════════════════════════════════════════════
# 5. POST /api/knowledge/import — 批量导入
# ═══════════════════════════════════════════════════════════

class TestKnowledgeImport:
    """KB 页面 → KB 引擎批量入库"""

    def test_import_returns_imported_count(self):
        """批量导入返回 imported/total"""
        with patch(
            "backend.src.api.main.knowledge_base.add_documents_batch",
            new_callable=AsyncMock,
            return_value=5
        ):
            response = client.post("/api/knowledge/import")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "imported" in data
            assert "total" in data


# ═══════════════════════════════════════════════════════════
# 6. GET /api/knowledge/search — 语义检索
# ═══════════════════════════════════════════════════════════

class TestKnowledgeSearch:
    """KB 页面/外部 → KB 引擎检索"""

    def test_search_empty_query_returns_empty_results(self):
        """空查询返回空结果"""
        response = client.get("/api/knowledge/search", params={"q": ""})
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == ""
        assert data["results"] == []

    def test_search_with_query_returns_results(self):
        """检索返回匹配 chunks"""
        with patch(
            "backend.src.api.main.knowledge_base.search",
            new_callable=AsyncMock,
            return_value=[
                {
                    "doc_id": "test1",
                    "doc_title": "FANUC 示教器",
                    "chunk_index": 0,
                    "content": "PTP 运动指令使用方法",
                    "relevance_score": 0.85,
                }
            ]
        ):
            response = client.get(
                "/api/knowledge/search",
                params={"q": "FANUC PTP", "top_k": 5}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "FANUC PTP"
            assert len(data["results"]) > 0
            assert "relevance_score" in data["results"][0]
            assert "doc_title" in data["results"][0]
            assert "content" in data["results"][0]

    def test_search_default_top_k(self):
        """默认 top_k=5"""
        with patch(
            "backend.src.api.main.knowledge_base.search",
            new_callable=AsyncMock,
            return_value=[]
        ) as mock:
            client.get("/api/knowledge/search", params={"q": "test"})
            mock.assert_called_once()
            call_kwargs = mock.call_args[1]
            assert call_kwargs["top_k"] == 5


# ═══════════════════════════════════════════════════════════
# 7. GET /api/knowledge/stats — 统计信息
# ═══════════════════════════════════════════════════════════

class TestKnowledgeStats:
    """KB 页面 → KB 引擎统计"""

    def test_stats_returns_kb_info(self):
        """返回模式/文档数/Chunk数"""
        with patch(
            "backend.src.api.main.knowledge_base.get_stats",
            new_callable=AsyncMock,
            return_value={
                "mode": "chroma",
                "total_documents": 10,
                "total_chunks": 50,
                "collection_name": "xinhua_kb",
            }
        ):
            response = client.get("/api/knowledge/stats")
            assert response.status_code == 200
            data = response.json()
            assert data["mode"] in ["chroma", "file", "unknown"]
            assert "total_documents" in data
            assert "total_chunks" in data


# ═══════════════════════════════════════════════════════════
# 8. DELETE /api/knowledge/{doc_id} — 删除文档
# ═══════════════════════════════════════════════════════════

class TestKnowledgeDelete:
    """管理操作 → KB 引擎删除"""

    def test_delete_existing_doc_returns_ok(self):
        """删除成功返回 ok"""
        with patch(
            "backend.src.api.main.knowledge_base.delete_document",
            new_callable=AsyncMock,
            return_value=True
        ):
            response = client.delete("/api/knowledge/test_doc_001")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["doc_id"] == "test_doc_001"

    def test_delete_nonexistent_returns_404(self):
        """删除不存在的文档返回 404"""
        with patch(
            "backend.src.api.main.knowledge_base.delete_document",
            new_callable=AsyncMock,
            return_value=False
        ):
            response = client.delete("/api/knowledge/nonexistent_doc")
            assert response.status_code == 404


# ═══════════════════════════════════════════════════════════
# 9. 异常处理覆盖
# ═══════════════════════════════════════════════════════════

class TestExceptionHandling:
    """Day 7 API 异常处理加固验证"""

    def test_kb_connection_error_returns_503(self):
        """KB 引擎下线 → 503"""
        with patch(
            "backend.src.api.main.knowledge_base.search",
            new_callable=AsyncMock,
            side_effect=ConnectionError("ChromaDB unavailable")
        ):
            response = client.get("/api/knowledge/search", params={"q": "test"})
            assert response.status_code == 503

    def test_kb_general_error_returns_500(self):
        """KB 异常 → 500"""
        with patch(
            "backend.src.api.main.knowledge_base.search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Unexpected error")
        ):
            response = client.get("/api/knowledge/search", params={"q": "test"})
            assert response.status_code == 500


# ═══════════════════════════════════════════════════════════
# 10. CORS 配置验证
# ═══════════════════════════════════════════════════════════

class TestCORS:
    """跨域请求支持"""

    def test_cors_headers_present(self):
        """CORS 中间件配置正确"""
        response = client.options(
            "/",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            }
        )
        assert "access-control-allow-origin" in {
            h.lower() for h in response.headers.keys()
        }


# ═══════════════════════════════════════════════════════════
# 运行说明
# ═══════════════════════════════════════════════════════════
"""
运行方式：
  cd C:\\Users\\123456\\XH-agent
  pytest backend/tests/test_api_endpoints.py -v

覆盖场景：
  ✓ 正常路径（6个端点）
  ✓ 参数校验（422）
  ✓ 文档不存在（404）
  ✓ KB 引擎异常（503/500）
  ✓ 硬性约束（出参结构）
  ✓ CORS 配置

预期结果：ALL PASS
"""
