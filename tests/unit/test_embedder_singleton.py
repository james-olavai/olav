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

    # 重置模块级缓存，确保每次测试独立
    import olav.core.embedder as embedder_mod

    original = embedder_mod._embedder
    embedder_mod._embedder = None

    try:
        with patch.dict(
            "sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=FakeST)}
        ):
            e1 = embedder_mod.get_embedder()
            e2 = embedder_mod.get_embedder()
            e3 = embedder_mod.get_embedder()
    finally:
        embedder_mod._embedder = original

    assert e1 is e2 is e3, "get_embedder() must return the same instance on every call."
    assert len(init_count) == 1, (
        f"SentenceTransformer.__init__ was called {len(init_count)} times. Expected 1."
    )


def test_get_embedder_returns_none_when_st_unavailable():
    """sentence_transformers 不可用时，get_embedder() 必须返回 None（不抛异常）。"""
    import olav.core.embedder as embedder_mod

    original = embedder_mod._embedder

    embedder_mod._embedder = None
    try:
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            result = embedder_mod.get_embedder()
    finally:
        embedder_mod._embedder = original

    assert result is None, (
        "get_embedder() must return None when sentence_transformers is unavailable."
    )


# ---------------------------------------------------------------------------
# PERF-1: KnowledgeBase._embed must delegate to get_embedder() singleton
# ---------------------------------------------------------------------------


def test_kb_embed_uses_singleton_when_dims_match():
    """KnowledgeBase._embed must call get_embedder() instead of creating its own SentenceTransformer.

    When the singleton's output dimension matches the KB table dimension,
    the singleton must be reused — no new SentenceTransformer created.
    """
    fake_model = MagicMock()
    fake_model.get_sentence_embedding_dimension.return_value = 384
    fake_model.encode.return_value = np.zeros(384, dtype=np.float32)

    with (
        patch("olav.core.knowledge.get_embedder", return_value=fake_model) as mock_get,
        patch("olav.core.config.get_embedding_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            mode="local",
            local_model="BAAI/bge-small-en-v1.5",
            device="cpu",
        )

        from olav.core.knowledge import KnowledgeBase

        store = MagicMock()
        store.table_exists.return_value = False
        kb = KnowledgeBase(store=store, embedding_dim=384)
        result = kb._embed("hello world")

    mock_get.assert_called()
    fake_model.encode.assert_called_once()
    assert result is not None, "_embed should return embeddings when singleton is available"


def test_kb_embed_falls_back_on_dim_mismatch():
    """When singleton dim ≠ table dim, KB must fall back to local SentenceTransformer.

    This preserves the dimension-compatibility safety logic.
    """
    # Singleton produces 384-dim but KB table expects 768-dim
    fake_singleton = MagicMock()
    fake_singleton.get_sentence_embedding_dimension.return_value = 384

    fake_fallback = MagicMock()
    fake_fallback.encode.return_value = np.zeros(768, dtype=np.float32)

    with (
        patch("olav.core.knowledge.get_embedder", return_value=fake_singleton),
        patch("olav.core.config.get_embedding_config") as mock_cfg,
    ):
        mock_cfg.return_value = MagicMock(
            mode="local",
            local_model="BAAI/bge-base-en-v1.5",
            device="cpu",
        )

        # Patch SentenceTransformer at the source module — _embed() does
        # ``from sentence_transformers import SentenceTransformer`` locally,
        # so we must patch the class in its home module.
        with patch("sentence_transformers.SentenceTransformer", return_value=fake_fallback):
            from olav.core.knowledge import KnowledgeBase

            store = MagicMock()
            store.table_exists.return_value = False
            kb = KnowledgeBase(store=store, embedding_dim=768)
            result = kb._embed("hello world")

    assert result is not None, "_embed should still work via fallback when dims mismatch"


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
