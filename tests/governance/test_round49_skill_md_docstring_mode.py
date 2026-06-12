"""Round 49 — ARCH-19 SKILL.md ``tools_docstring_mode`` field.

Completes the last actionable ARCH-19 gap: agents can declaratively pin
their preferred docstring mode in SKILL.md frontmatter, overriding the
tier default without requiring every caller to pass ``detail=``
explicitly.

Precedence in ``_resolve_detail``:
    1. Explicit ``detail=`` kwarg.
    2. Agent's ``SKILL.md::tools_docstring_mode`` (when ``agent_id`` is
       passed; accepts ``compact`` / ``brief`` / ``full`` / ``long``).
    3. ``TIER_DEFAULTS[<tier>]["tool_help_detail"]``.
    4. Static fallback (``"full"``).

Governance pins:

* ``_SKILL_MODE_ALIASES`` covers the full vocabulary
* ``_read_agent_docstring_mode`` reads SKILL.md (end-to-end smoke on a tmp dir)
* ``_resolve_detail(detail=None, agent_id=...)`` honours the override
* ``tool_help(name, agent_id=...)`` signature exposes the new kwarg
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL_HELP_PY = REPO / ".olav" / "workspace" / "admin" / "editor" / "scripts" / "tool_help.py"


def _load():
    spec = importlib.util.spec_from_file_location("_olav_tool_help_r49", TOOL_HELP_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Alias vocabulary pins ─────────────────────────────────────────────


def test_skill_mode_aliases_cover_spec_vocabulary():
    mod = _load()
    aliases = mod._SKILL_MODE_ALIASES
    # v0.18.1 spec wording is "compact"; tool_help(detail=) uses "brief" —
    # both must resolve to the same canonical level.
    assert aliases["compact"] == "brief"
    assert aliases["brief"] == "brief"
    # Common synonyms — tolerant to avoid surprising spec drift later.
    for k in ("short",):
        assert aliases[k] == "brief"
    for k in ("full", "long", "verbose"):
        assert aliases[k] == "full"


def test_aliases_all_map_to_valid_detail():
    mod = _load()
    for src, dst in mod._SKILL_MODE_ALIASES.items():
        assert dst in mod._VALID_DETAIL, (
            f"alias {src!r} → {dst!r} not in _VALID_DETAIL"
        )


# ── SKILL.md reader pins ──────────────────────────────────────────────


def test_reader_helper_exists():
    mod = _load()
    assert callable(getattr(mod, "_read_agent_docstring_mode", None))


def test_reader_returns_none_for_empty_or_bad_agent_id():
    mod = _load()
    assert mod._read_agent_docstring_mode("") is None
    assert mod._read_agent_docstring_mode(None) is None  # type: ignore[arg-type]
    assert mod._read_agent_docstring_mode("   ") is None
    assert mod._read_agent_docstring_mode("definitely_not_an_agent_xyz") is None


def test_reader_resolves_real_agent_skill_md(tmp_path, monkeypatch):
    """Patch the module's workspace roots so the reader finds a fake
    agent's SKILL.md with a compact declaration."""
    mod = _load()

    fake_workspace = tmp_path / ".olav" / "workspace"
    agent_dir = fake_workspace / "fake_agent"
    tools_dir = agent_dir / "tools"
    tools_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text(
        "---\n"
        "name: fake_agent\n"
        "tools_docstring_mode: compact\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_TOOL_ROOTS", [tools_dir])

    assert mod._read_agent_docstring_mode("fake_agent") == "brief"


def test_reader_ignores_missing_frontmatter(tmp_path, monkeypatch):
    mod = _load()

    fake_workspace = tmp_path / ".olav" / "workspace"
    agent_dir = fake_workspace / "agent_no_frontmatter"
    (agent_dir / "tools").mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("# Just a markdown file\n", encoding="utf-8")

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_TOOL_ROOTS", [agent_dir / "tools"])
    assert mod._read_agent_docstring_mode("agent_no_frontmatter") is None


def test_reader_ignores_unknown_mode_value(tmp_path, monkeypatch):
    """A typo like ``tools_docstring_mode: gibberish`` must resolve to None
    so callers can fall through to tier defaults — never crash."""
    mod = _load()

    fake_workspace = tmp_path / ".olav" / "workspace"
    agent_dir = fake_workspace / "agent_typo"
    (agent_dir / "tools").mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text(
        "---\nname: agent_typo\ntools_docstring_mode: gibberish\n---\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_TOOL_ROOTS", [agent_dir / "tools"])
    assert mod._read_agent_docstring_mode("agent_typo") is None


# ── _resolve_detail precedence pins ───────────────────────────────────


def test_resolve_detail_explicit_beats_agent(tmp_path, monkeypatch):
    """Explicit detail kwarg must win even when agent has a SKILL.md
    declaration (operator override for debugging)."""
    mod = _load()

    fake_workspace = tmp_path / ".olav" / "workspace"
    agent_dir = fake_workspace / "small_agent"
    (agent_dir / "tools").mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text(
        "---\nname: small_agent\ntools_docstring_mode: compact\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_TOOL_ROOTS", [agent_dir / "tools"])

    assert mod._resolve_detail("full", agent_id="small_agent") == "full"
    assert mod._resolve_detail("brief", agent_id="small_agent") == "brief"


def test_resolve_detail_agent_beats_tier(tmp_path, monkeypatch):
    mod = _load()

    fake_workspace = tmp_path / ".olav" / "workspace"
    agent_dir = fake_workspace / "opinionated_agent"
    (agent_dir / "tools").mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text(
        "---\nname: opinionated_agent\ntools_docstring_mode: full\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_TOOL_ROOTS", [agent_dir / "tools"])

    # No explicit detail + agent says "full" — result must be "full"
    # regardless of the active tier.
    assert mod._resolve_detail(None, agent_id="opinionated_agent") == "full"


def test_resolve_detail_no_agent_falls_back_to_tier():
    """With no agent context the old tier-driven path still works."""
    mod = _load()
    result = mod._resolve_detail(None)
    assert result in mod._VALID_DETAIL


# ── tool_help signature pin ───────────────────────────────────────────


def test_tool_help_signature_exposes_agent_id():
    import inspect
    mod = _load()
    # Post-scripts-化: tool_help is a plain function; check via inspect.signature.
    # Legacy @tool path: check args_schema; plain-function path: check signature.
    schema = getattr(mod.tool_help, "args_schema", None)
    if schema is not None:
        fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
        assert "agent_id" in fields, (
            f"tool_help must expose agent_id in its args_schema; got {list(fields)}"
        )
        agent_field = fields["agent_id"]
        required = getattr(agent_field, "is_required", None)
        if callable(required):
            required = required()
        assert required is False, "agent_id must be optional"
    else:
        sig = inspect.signature(mod.tool_help)
        assert "agent_id" in sig.parameters, (
            f"tool_help must expose agent_id parameter; got {list(sig.parameters)}"
        )
        param = sig.parameters["agent_id"]
        assert param.default is not inspect.Parameter.empty, "agent_id must have a default (be optional)"
