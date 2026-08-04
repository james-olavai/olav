"""R100/S3 — embed_text input truncation against server batch_size limit.

llama-server with --batch-size N returns 500 ``input too large`` when
input exceeds N tokens.  OLAV AutoCapture embeds the growing
conversation history each turn, which can exceed the cap.  The
default 6000-char clip is a safe upper bound (≈ 1500-2000 tokens
for typical mixed content).
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def test_short_text_passes_through_unchanged():
    """Inputs under the cap reach the API verbatim."""
    from olav.core import embedder

    fake_cfg = MagicMock()
    fake_cfg.mode = "api"
    with patch("olav.core.embedder._get_api_client") as mock_client, \
         patch("olav.core.config.get_embedding_config", return_value=fake_cfg):
        client = MagicMock()
        client.embeddings.create.return_value.data = [
            MagicMock(embedding=[0.1] * 32)
        ]
        mock_client.return_value = (client, "x")
        embedder._embed_cache.clear()

        embedder.embed_text("hello world")

        sent = client.embeddings.create.call_args.kwargs["input"]
        assert sent == "hello world"


def test_long_text_truncated_to_default_cap(monkeypatch):
    """Inputs > 6000 chars get clipped before API call.

    Every other test in this file sets OLAV_EMBED_MAX_CHARS explicitly; this one
    asserts the DEFAULT, so it has to clear the variable rather than assume the
    ambient environment has not set it. `.gitea/workflows/ci.yml` pins
    OLAV_EMBED_MAX_CHARS=1000 (the embed server's 512-token ubatch returns HTTP
    500 above ~1000 chars), so this failed in CI with `assert 1000 == 6000` while
    passing on every dev box — and the failure was invisible because that job's
    step carried continue-on-error.
    """
    monkeypatch.delenv("OLAV_EMBED_MAX_CHARS", raising=False)
    from olav.core import embedder

    long_text = "x" * 9000
    fake_cfg = MagicMock()
    fake_cfg.mode = "api"
    with patch("olav.core.embedder._get_api_client") as mock_client, \
         patch("olav.core.config.get_embedding_config", return_value=fake_cfg):
        client = MagicMock()
        client.embeddings.create.return_value.data = [
            MagicMock(embedding=[0.1] * 32)
        ]
        mock_client.return_value = (client, "x")
        embedder._embed_cache.clear()

        embedder.embed_text(long_text)

        sent = client.embeddings.create.call_args.kwargs["input"]
        assert len(sent) == 6000


def test_env_var_overrides_default_cap(monkeypatch):
    """OLAV_EMBED_MAX_CHARS=2000 caps to 2000."""
    from olav.core import embedder

    monkeypatch.setenv("OLAV_EMBED_MAX_CHARS", "2000")
    long_text = "y" * 5000
    fake_cfg = MagicMock()
    fake_cfg.mode = "api"
    with patch("olav.core.embedder._get_api_client") as mock_client, \
         patch("olav.core.config.get_embedding_config", return_value=fake_cfg):
        client = MagicMock()
        client.embeddings.create.return_value.data = [
            MagicMock(embedding=[0.1] * 32)
        ]
        mock_client.return_value = (client, "x")
        embedder._embed_cache.clear()

        embedder.embed_text(long_text)

        sent = client.embeddings.create.call_args.kwargs["input"]
        assert len(sent) == 2000


def test_env_var_zero_disables_cap(monkeypatch):
    """OLAV_EMBED_MAX_CHARS=0 means no truncation."""
    from olav.core import embedder

    monkeypatch.setenv("OLAV_EMBED_MAX_CHARS", "0")
    long_text = "z" * 9000
    fake_cfg = MagicMock()
    fake_cfg.mode = "api"
    with patch("olav.core.embedder._get_api_client") as mock_client, \
         patch("olav.core.config.get_embedding_config", return_value=fake_cfg):
        client = MagicMock()
        client.embeddings.create.return_value.data = [
            MagicMock(embedding=[0.1] * 32)
        ]
        mock_client.return_value = (client, "x")
        embedder._embed_cache.clear()

        embedder.embed_text(long_text)

        sent = client.embeddings.create.call_args.kwargs["input"]
        assert len(sent) == 9000


def test_env_var_invalid_falls_back_to_default(monkeypatch):
    """Bad env value (non-int) falls back to default 6000."""
    from olav.core import embedder

    monkeypatch.setenv("OLAV_EMBED_MAX_CHARS", "abc")
    long_text = "w" * 9000
    fake_cfg = MagicMock()
    fake_cfg.mode = "api"
    with patch("olav.core.embedder._get_api_client") as mock_client, \
         patch("olav.core.config.get_embedding_config", return_value=fake_cfg):
        client = MagicMock()
        client.embeddings.create.return_value.data = [
            MagicMock(embedding=[0.1] * 32)
        ]
        mock_client.return_value = (client, "x")
        embedder._embed_cache.clear()

        embedder.embed_text(long_text)

        sent = client.embeddings.create.call_args.kwargs["input"]
        assert len(sent) == 6000
