"""ARCH-17 (Round 36) — ``OLAV_DEBUG_CONTEXT`` operator toggle.

Pins the debug-logging contract for static_context injection:

* ``static_context_resolver._DEBUG_ENV_VAR`` is named ``OLAV_DEBUG_CONTEXT``.
* ``is_debug_enabled()`` accepts the documented truthy set and rejects
  everything else (prevents drift from ``OLAV_DEBUG_CONTEXT=0``
  accidentally turning it on).
* The module docstring advertises the env var so operators can find it.
* ``agent._debug_log_injection`` exists and no-ops without the env var.

The runtime emit path is exercised end-to-end via a smoke that calls
``_inject_static_context`` against a tiny temp skill dir with the env
var flipped on, then captures log output and asserts the expected
format fields.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RESOLVER_PATH = REPO / "src" / "olav" / "agents" / "static_context_resolver.py"
AGENT_PATH = REPO / "src" / "olav" / "agents" / "agent.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


resolver_mod = _load(RESOLVER_PATH, "static_context_resolver_for_debug_test")


def _load_agent_module():
    pytest.importorskip("langchain_community")
    return _load(AGENT_PATH, "agent_for_debug_context_test")


# ── constant pins ──────────────────────────────────────────────────────────


def test_debug_env_var_name_pinned():
    assert resolver_mod._DEBUG_ENV_VAR == "OLAV_DEBUG_CONTEXT"


def test_debug_truthy_set_pinned():
    assert resolver_mod._DEBUG_TRUTHY == frozenset({"1", "true", "yes", "on"})


def test_is_debug_enabled_is_public_callable():
    assert callable(getattr(resolver_mod, "is_debug_enabled", None))


def test_module_docstring_advertises_debug_env():
    doc = resolver_mod.__doc__ or ""
    assert "OLAV_DEBUG_CONTEXT" in doc, (
        "resolver docstring must advertise the OLAV_DEBUG_CONTEXT operator "
        "env var so it shows up in `help(static_context_resolver)`."
    )


def test_agent_has_debug_log_injection_helper():
    src = AGENT_PATH.read_text(encoding="utf-8")
    assert "def _debug_log_injection(" in src


@pytest.fixture
def agent_mod():
    return _load_agent_module()


def test_agent_module_exposes_debug_log_injection_helper(agent_mod):
    fn = getattr(agent_mod, "_debug_log_injection", None)
    assert callable(fn), "agent._debug_log_injection must be defined"


# ── is_debug_enabled behaviour ─────────────────────────────────────────────


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON"])
def test_is_debug_enabled_truthy(monkeypatch, val):
    monkeypatch.setenv("OLAV_DEBUG_CONTEXT", val)
    assert resolver_mod.is_debug_enabled() is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "foo", "2"])
def test_is_debug_enabled_falsy(monkeypatch, val):
    monkeypatch.setenv("OLAV_DEBUG_CONTEXT", val)
    assert resolver_mod.is_debug_enabled() is False


def test_is_debug_enabled_unset(monkeypatch):
    monkeypatch.delenv("OLAV_DEBUG_CONTEXT", raising=False)
    assert resolver_mod.is_debug_enabled() is False


# ── end-to-end smoke: env on → log record emitted with format fields ──────


def _capture_info_logs(caplog) -> str:
    return "\n".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.INFO
    )


def test_debug_log_emitted_for_always_mode(agent_mod, monkeypatch, tmp_path, caplog):
    """End-to-end: OLAV_DEBUG_CONTEXT=1 + mode=always → summary log line."""
    monkeypatch.setenv("OLAV_DEBUG_CONTEXT", "1")

    skill_dir = tmp_path / "tiny_agent"
    refs = skill_dir / "references"
    refs.mkdir(parents=True)
    (refs / "SAMPLE.md").write_text("hello world\n" * 10, encoding="utf-8")

    metadata = {
        "static_context": [{"path": "./references/SAMPLE.md"}],
        "static_context_mode": "always",
    }

    caplog.set_level(logging.INFO, logger=agent_mod.logger.name)
    out = agent_mod._inject_static_context("BASE PROMPT", skill_dir, metadata)
    log_text = _capture_info_logs(caplog)

    assert "BASE PROMPT" in out
    assert "SAMPLE.md" in out
    assert "OLAV_DEBUG_CONTEXT:" in log_text, (
        f"debug summary not emitted; captured logs:\n{log_text}"
    )
    assert "agent=tiny_agent" in log_text
    assert "mode=always" in log_text
    assert "SAMPLE.md" in log_text
    assert "injected:" in log_text


def test_debug_log_emitted_for_on_intent_skip(agent_mod, monkeypatch, tmp_path, caplog):
    """on_intent mode with skip path still emits the summary (0 injected)."""
    monkeypatch.setenv("OLAV_DEBUG_CONTEXT", "1")
    monkeypatch.setenv("OLAV_STATIC_CONTEXT_MODE", "lazy")  # force skip

    skill_dir = tmp_path / "lazy_agent"
    refs = skill_dir / "references"
    refs.mkdir(parents=True)
    (refs / "A.md").write_text("a\n", encoding="utf-8")
    (refs / "B.md").write_text("b\n", encoding="utf-8")

    metadata = {
        "static_context": [
            {"path": "./references/A.md"},
            {"path": "./references/B.md"},
        ],
    }

    caplog.set_level(logging.INFO, logger=agent_mod.logger.name)
    agent_mod._inject_static_context("P", skill_dir, metadata)
    log_text = _capture_info_logs(caplog)

    assert "OLAV_DEBUG_CONTEXT:" in log_text
    assert "mode=lazy" in log_text
    assert "skipped init inject" in log_text


def test_debug_log_suppressed_when_env_unset(agent_mod, monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("OLAV_DEBUG_CONTEXT", raising=False)

    skill_dir = tmp_path / "silent"
    refs = skill_dir / "references"
    refs.mkdir(parents=True)
    (refs / "X.md").write_text("x", encoding="utf-8")

    metadata = {
        "static_context": [{"path": "./references/X.md"}],
        "static_context_mode": "always",
    }

    caplog.set_level(logging.INFO, logger=agent_mod.logger.name)
    agent_mod._inject_static_context("P", skill_dir, metadata)
    log_text = _capture_info_logs(caplog)

    assert "OLAV_DEBUG_CONTEXT:" not in log_text
