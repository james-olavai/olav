"""TDD (dev_docs/77 §2.6.3, plan Phase 4): analyzer must declare
``sim`` in its ``subagents:`` list so deepagents auto-injects the
``task`` tool, enabling cross-domain delegation
(analyzer → task("sim", "<config question>")).

Sister test to ``test_agent_recursive_deep_agent.py`` which verifies
the framework-level wiring; this one verifies the analyzer's
SKILL.md actually declares the relationship.
"""
from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest


REPO = Path(__file__).resolve().parent.parent.parent
ANALYZER_SKILL = REPO / "olav-netops/.olav/workspace/netops/analyzer/SKILL.md"
ANALYZER_SYSTEM = REPO / "olav-netops/.olav/workspace/netops/analyzer/prompts/system.md"


def _load_analyzer_metadata() -> dict:
    if not ANALYZER_SKILL.exists():
        pytest.fail(f"analyzer SKILL.md not found at {ANALYZER_SKILL}")
    with ANALYZER_SKILL.open(encoding="utf-8") as f:
        post = frontmatter.load(f)
    return post.metadata or {}


def test_analyzer_declares_sim_as_subagent():
    """analyzer/SKILL.md must declare sim in subagents: so the recursive
    create_deep_agent branch (agent.py post-Phase-1) wires task() for
    cross-domain delegation."""
    meta = _load_analyzer_metadata()
    subagents = meta.get("subagents") or []
    assert subagents, (
        "analyzer/SKILL.md must declare a non-empty subagents: list "
        "to enable cross-domain delegation per dev_docs/77 §2.6"
    )
    paths = [
        (s["path"] if isinstance(s, dict) else s)
        for s in subagents
    ]
    assert any("sim/SKILL.md" in p for p in paths), (
        f"analyzer must declare ../sim/SKILL.md in subagents:; got {paths}"
    )


def test_analyzer_is_not_agent_type_api():
    """A sub-agent declared as ``agent_type: api`` is treated as a leaf
    (no TodoListMiddleware, no recursive deep-agent build).  Analyzer
    must NOT be api because it now needs to dispatch via task()."""
    meta = _load_analyzer_metadata()
    agent_type = (meta.get("agent_type") or "").strip().lower()
    assert agent_type not in ("api", "query"), (
        f"analyzer must NOT be agent_type: api now that it delegates to "
        f"sim; got agent_type={agent_type!r}"
    )


def test_analyzer_system_prompt_mentions_delegation_to_sim():
    """analyzer/prompts/system.md must teach the analyzer how to
    delegate config-layer questions to sim via task("sim", ...).
    Phase 2.5 DELEGATION block per dev_docs/77 §2.6.4."""
    assert ANALYZER_SYSTEM.exists(), \
        f"analyzer prompts/system.md not found at {ANALYZER_SYSTEM}"
    text = ANALYZER_SYSTEM.read_text(encoding="utf-8")
    assert 'task("sim"' in text or "task('sim'" in text, (
        "analyzer system.md must teach delegation via "
        "task('sim', ...) — Phase 2.5 DELEGATION per dev_docs/77 §2.6.4"
    )
    # Also expect a section header / phase tag so the workflow is obvious
    assert "DELEGATION" in text or "Phase 2.5" in text, (
        "analyzer system.md must have an explicit DELEGATION phase "
        "(text 'DELEGATION' or 'Phase 2.5') in Workflow A and/or D"
    )
