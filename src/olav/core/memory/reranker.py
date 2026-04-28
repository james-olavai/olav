"""LanceDB reranker that uses an Ollama-served reranker model as a
second-stage relevance scorer.

Why not the LanceDB-native ``CrossEncoderReranker``: that loads a
HuggingFace cross-encoder via ``sentence_transformers`` directly,
which adds 600+ MB of optional ML deps to OLAV's wheel and bypasses
the Ollama box already running OLAV's embedder + LLM.

Why not a true cross-encoder over Ollama: as of Ollama 0.21, models
packaged for the platform expose ``/api/embeddings`` and ``/api/generate``
endpoints — the BERT-style cross-encoder rerank head (CLS → linear
classifier → score) isn't preserved through the GGUF conversion. So
we treat the reranker model as a **second-stage embedder** with a
different latent space than the first-stage embedder, and rerank
candidates by cosine similarity in that space.

This is **bi-encoder ensemble**, not true cross-encoder rerank.
Empirically: a reranker model's embedding latent space tends to
encode "relevance to query" better than a general-purpose embedder
encodes "topical similarity". Two-stage ensemble lifts top-K
precision even without cross-encoder semantics.

Tier 1 ships this. If we later need true cross-encoder, swap the
HTTP endpoint for a FlagEmbedding direct load (or a cross-encoder
service deployed alongside Ollama).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa

from lancedb.rerankers.base import Reranker

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class OllamaEmbeddingReranker(Reranker):
    """Rerank candidates by cosine similarity in a reranker model's
    embedding space, served via Ollama's ``/api/embeddings`` endpoint.

    Args:
        model_name: Ollama model tag (e.g. ``"bbjson/bge-reranker-base"``).
        base_url: Ollama base URL. Defaults to ``http://localhost:11434``.
        column: Name of the text column in candidate rows. Default ``"text"``.
        cache_size: Max cached embeddings (LRU). 0 disables.
        return_score: ``"relevance"`` (default) or ``"all"`` per LanceDB convention.
    """

    def __init__(
        self,
        model_name: str = "bbjson/bge-reranker-base",
        base_url: str = "http://localhost:11434",
        column: str = "text",
        cache_size: int = 1024,
        return_score: str = "relevance",
    ):
        super().__init__(return_score=return_score)
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.column = column
        self._cache: dict[str, list[float]] = {}
        self._cache_size = cache_size
        self._http = None

    def _get_http(self):
        if self._http is None:
            import httpx
            self._http = httpx.Client(timeout=15.0)
        return self._http

    def _embed_one(self, text: str) -> "list[float] | None":
        """Embed a single text via Ollama. Returns None on failure."""
        if not text:
            return None
        if self._cache_size > 0 and text in self._cache:
            return self._cache[text]
        try:
            resp = self._get_http().post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model_name, "prompt": text},
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding")
            if vec is None:
                return None
            if self._cache_size > 0:
                if len(self._cache) >= self._cache_size:
                    # Drop oldest (insertion order in dict)
                    self._cache.pop(next(iter(self._cache)))
                self._cache[text] = vec
            return vec
        except Exception as exc:
            logger.debug("OllamaEmbeddingReranker embed failed: %s", exc)
            return None

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        if denom <= 0:
            return 0.0
        return float(np.dot(va, vb) / denom)

    def _score_table(self, query: str, table: pa.Table) -> pa.Table:
        """Add / overwrite a ``_relevance_score`` column on the table by
        cosine-similarity between the rerank-model embedding of query
        and each row's text."""
        if table.num_rows == 0:
            return table.append_column(
                "_relevance_score", pa.array([], type=pa.float32())
            )
        if self.column not in table.column_names:
            logger.warning(
                "OllamaEmbeddingReranker: column %r missing from table; "
                "returning original order with NaN scores",
                self.column,
            )
            scores = pa.array([float("nan")] * table.num_rows, type=pa.float32())
            return table.append_column("_relevance_score", scores)

        query_vec = self._embed_one(query)
        texts = table.column(self.column).to_pylist()
        scores: list[float] = []
        for t in texts:
            if query_vec is None:
                scores.append(float("nan"))
                continue
            doc_vec = self._embed_one(str(t) if t is not None else "")
            if doc_vec is None:
                scores.append(float("nan"))
                continue
            scores.append(self._cosine(query_vec, doc_vec))

        # Drop existing _relevance_score if the underlying search produced one
        if "_relevance_score" in table.column_names:
            table = table.drop_columns(["_relevance_score"])
        result = table.append_column(
            "_relevance_score", pa.array(scores, type=pa.float32())
        )
        # Sort descending by score; NaN scores sink to bottom
        order = np.argsort(scores, kind="stable")[::-1].tolist()
        return result.take(order)

    # ── LanceDB Reranker interface ─────────────────────────────────────

    def rerank_vector(self, query: str, vector_results: pa.Table) -> pa.Table:
        return self._score_table(query, vector_results)

    def rerank_fts(self, query: str, fts_results: pa.Table) -> pa.Table:
        return self._score_table(query, fts_results)

    def rerank_hybrid(
        self,
        query: str,
        vector_results: pa.Table,
        fts_results: pa.Table,
    ) -> pa.Table:
        merged = self.merge_results(vector_results, fts_results)
        return self._score_table(query, merged)
