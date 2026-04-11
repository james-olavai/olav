"""Phase 2-1 TDD: core/embedder.py 全局共享 SentenceTransformer 单例

断言：
- get_embedder() 可以 import
- 多次调用返回同一对象（is 比较）
- SentenceTransformer.__init__ 只被调用 1 次
- KnowledgeBase._embed uses the singleton (PERF-1)
- LLMFactory.get_embeddings uses the singleton (PERF-1)
"""

import sys
from unittest.mock import MagicMock, patch

import numpy as np


def test_get_embedder_importable():
    """olav.core.embedder.get_embedder 必须可 import。"""
    from olav.core.embedder import get_embedder  # noqa: F401


def test_get_embedder_returns_singleton():
    """多次调用 get_embedder() 必须返回同一对象（模块级单例）。"""
    init_count = []

    class FakeST:
        def __init__(self, model, *a, **kw):
            init_count.append(model)

        def get_sentence_embedding_dimension(self):
            return 384

    # 重置模块级缓存，确保每次测试独立
    import olav.core.embedder as embedder_mod

    original = embedder_mod._local_embedder
    embedder_mod._local_embedder = None

    fake_cfg = MagicMock(mode="local", local_model="BAAI/bge-small-en-v1.5", device="cpu")

    try:
        with (
            patch.dict("sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=FakeST)}),
            patch("olav.core.config.get_embedding_config", return_value=fake_cfg),
        ):
            e1 = embedder_mod.get_embedder()
            e2 = embedder_mod.get_embedder()
            e3 = embedder_mod.get_embedder()
    finally:
        embedder_mod._local_embedder = original

    assert e1 is e2 is e3, "get_embedder() must return the same instance on every call."
    assert len(init_count) == 1, (
        f"SentenceTransformer.__init__ was called {len(init_count)} times. Expected 1."
    )


def test_get_embedder_returns_none_when_st_unavailable():
    """sentence_transformers 不可用时，get_embedder() 必须返回 None（不抛异常）。"""
    import olav.core.embedder as embedder_mod

    original = embedder_mod._local_embedder

    embedder_mod._local_embedder = None
    try:
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            result = embedder_mod.get_embedder()
    finally:
        embedder_mod._local_embedder = original

    assert result is None, (
        "get_embedder() must return None when sentence_transformers is unavailable."
    )


# ---------------------------------------------------------------------------
# PERF-1: LLMFactory.get_embeddings must delegate to get_embedder() singleton
# ---------------------------------------------------------------------------


def test_llm_get_embeddings_uses_singleton():
    """LLMFactory.get_embeddings (local mode) must use get_embedder() singleton.

    The wrapper class must still expose embed_documents() and embed_query().
    """
    fake_model = MagicMock()
    fake_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)

    with (
        patch("olav.core.llm.get_embedder", return_value=fake_model) as mock_get,
        patch("olav.core.config.get_embedding_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            mode="local",
            local_model="BAAI/bge-small-en-v1.5",
            device="cpu",
            normalize_embeddings=True,
            fallback_enabled=False,
        )

        from olav.core.llm import LLMFactory

        wrapper = LLMFactory.get_embeddings()

    mock_get.assert_called()
    # Verify LangChain-compatible API shape
    assert hasattr(wrapper, "embed_documents"), "Wrapper must have embed_documents()"
    assert hasattr(wrapper, "embed_query"), "Wrapper must have embed_query()"
