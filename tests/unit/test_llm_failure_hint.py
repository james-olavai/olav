"""_llm_failure_hint — runtime LLM failure → actionable recovery line
(dev_docs/99 §7.2).

Covers:
1. auth-shaped errors (401 / AuthenticationError / "api key") → key advice
2. quota-shaped errors (429 / 402 / RateLimitError / quota) → quota advice
3. connection-shaped errors (APIConnectionError/APITimeoutError) → endpoint advice
4. generic API errors → generic cause, still pointing at doctor + rollback
5. non-API errors (DB, filesystem, ValueError) → None, no LLM advice
6. wiring: cli_main_impl prints the hint (and skips the traceback) for an
   API-shaped error escaping the main flow
"""

from __future__ import annotations

import asyncio
import io
import sys

import pytest
from rich.console import Console

import olav.cli.main as main_mod
from olav.cli.main import _llm_failure_hint


def test_auth_error_names_the_key() -> None:
    hint = _llm_failure_hint(
        Exception("Error code: 401 - {'error': {'message': 'Authentication Fails'}}")
    )
    assert hint is not None
    assert "API key" in hint
    assert "olav doctor" in hint
    assert "rollback" in hint


def test_quota_error_names_quota() -> None:
    hint = _llm_failure_hint(Exception("Error code: 429 - rate limit exceeded"))
    assert hint is not None
    assert "quota" in hint.lower() or "rate-limiting" in hint


def test_connection_error_names_endpoint() -> None:
    class APIConnectionError(Exception):
        pass

    hint = _llm_failure_hint(APIConnectionError("Connection error."))
    assert hint is not None
    assert "unreachable" in hint


def test_timeout_is_not_reported_as_unreachable() -> None:
    """A per-request timeout means the endpoint answered but the model was
    slow (common for local llama.cpp/Ollama) — it must NOT be called
    'unreachable', and must point at the llm.timeout knob."""
    class APITimeoutError(Exception):
        pass

    hint = _llm_failure_hint(APITimeoutError("Request timed out."))
    assert hint is not None
    assert "unreachable" not in hint.lower()
    assert "timed out" in hint.lower()
    assert "llm.timeout" in hint

    # Bare 'Request timed out.' (langchain re-raise, no APITimeoutError class name)
    # must also classify as timeout, not fall through to unreachable/None.
    hint2 = _llm_failure_hint(Exception("Error: Request timed out."))
    assert hint2 is not None
    assert "llm.timeout" in hint2
    assert "unreachable" not in hint2.lower()


def test_generic_api_error_still_hints() -> None:
    class APIStatusError(Exception):
        pass

    hint = _llm_failure_hint(APIStatusError("service unavailable"))
    assert hint is not None
    assert "olav doctor" in hint


def test_non_api_errors_get_no_llm_advice() -> None:
    assert _llm_failure_hint(ValueError("column not found in netops.devices")) is None
    assert _llm_failure_hint(FileNotFoundError("/tmp/missing.parquet")) is None
    assert _llm_failure_hint(ConnectionError("db socket refused")) is None  # not API-shaped


def test_cli_main_impl_prints_hint_for_api_error(monkeypatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(main_mod, "console", Console(file=buf, width=200))

    def _raise(*a, **kw):
        raise Exception("Error code: 401 - Unauthorized: invalid api key")

    monkeypatch.setattr(main_mod, "parse_args", _raise)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(main_mod.cli_main_impl())

    assert exc_info.value.code == 1
    out = buf.getvalue()
    assert "olav doctor" in out
    assert "rollback my LLM config" in out


def test_cli_main_impl_no_hint_for_non_api_error(monkeypatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(main_mod, "console", Console(file=buf, width=200))

    def _raise(*a, **kw):
        raise ValueError("some internal bug")

    monkeypatch.setattr(main_mod, "parse_args", _raise)

    with pytest.raises(SystemExit):
        asyncio.run(main_mod.cli_main_impl())

    assert "olav doctor" not in buf.getvalue()
