"""Rounds 21-22 — user-facing docs must only invoke live agents.

Scope:
* Round 21 covered ``dev_docs/42. DEMO_RUNSHEET.md`` (customer demo runbook).
* Round 22 adds ``README.md`` + ``src/README_ZH.md`` (shipped with the pip
  package — the first thing new users copy/paste).

Every ``olav --agent <name>`` invocation in any of these live docs has to
resolve against the real v0.18.1 top-level agent set. Stale invocations
(``audit-designer``, ``ops-lab``, ``infra``, ``devops``, etc.) broke
silently across Rounds 17-18 when those agents were merged or deleted —
this test pins the fix.

If you add a new top-level agent directory, update ``CURRENT_AGENTS`` below.
If you rename/delete one, update it AND fix any outdated examples in the
live docs guarded here.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DEMO_RUNSHEET = REPO / "dev_docs" / "42. DEMO_RUNSHEET.md"
WORKSPACE = REPO / ".olav" / "workspace"

# Shipped with the pip package — first examples new users see.
USER_FACING_DOCS = (
    REPO / "README.md",
    REPO / "src" / "README_ZH.md",
    DEMO_RUNSHEET,
)


# Explicit allowlist — must match real top-level agent directories under
# .olav/workspace/ (excluding PLATFORM.md which is a file, not a dir).
# Update this set whenever you add, rename, or delete a top-level agent.
# Current state (dev_docs/85 AGENT_ARCHITECTURE_V2):
#   admin          — platform self-management (renamed from services)
#   audit          — audit orchestrator (runner/author/curator/explorer)
#   core           — cross-domain orchestrator
#   devops         — infra/scripts sub-agents
#   netops         — network domain (analyzer/collect/learner/sim/topology); learner/ handles parser learning
#   ops            — legacy shell; contains netops_init only (transitional)
CURRENT_AGENTS: frozenset[str] = frozenset({
    "admin",
    "audit",
    "core",
    "devops",
    "netops",
    "ops",
})


# Agents we know were merged/deleted; examples using them are regressions.
DELETED_AGENTS: frozenset[str] = frozenset({
    "audit-designer",      # → audit (Round 17 Step B)
    "audit-auditor",       # → audit (Round 17 Step B)
    "ops-lab",             # top-level shell → ops (Round 18 Step D lite)
    "infra",               # → services (Round 16 Step A + ARCH-20 P1)
    "services",            # → admin (dev_docs/85 AGENT_ARCHITECTURE_V2)
    "gitea",               # removed (ARCH-20 P1)
    "config",              # → core/admin/ (ARCH-20 P1)
})


_AGENT_INVOCATION = re.compile(r"olav\s+--agent\s+([a-zA-Z0-9_-]+)\b")


def test_demo_runsheet_exists():
    assert DEMO_RUNSHEET.is_file(), f"demo runsheet missing: {DEMO_RUNSHEET}"


def test_demo_runsheet_only_invokes_live_agents():
    """Every ``--agent <name>`` in the runsheet references a live top-level agent."""
    text = DEMO_RUNSHEET.read_text(encoding="utf-8")
    invocations = _AGENT_INVOCATION.findall(text)
    stale = [name for name in invocations if name not in CURRENT_AGENTS]
    assert not stale, (
        f"Demo runsheet invokes non-existent --agent {set(stale)}. "
        f"Live set is {sorted(CURRENT_AGENTS)}."
    )


def test_demo_runsheet_does_not_invoke_deleted_agents():
    """Tighter guard: explicitly forbid known-deleted names (catches regressions
    where someone copy-pastes an old example)."""
    text = DEMO_RUNSHEET.read_text(encoding="utf-8")
    invocations = set(_AGENT_INVOCATION.findall(text))
    leaked = invocations & DELETED_AGENTS
    assert not leaked, (
        f"Demo runsheet still invokes deleted agent(s) {sorted(leaked)}. "
        "These were merged/removed in ARCH-20 P1, Round 16 Step A, Round 17 "
        "Step B, or Round 18 Step D lite."
    )


def test_current_agents_set_matches_workspace():
    """``CURRENT_AGENTS`` above must match ``.olav/workspace/`` directories —
    otherwise this test drifts out of sync and gives false passes."""
    actual = {p.name for p in WORKSPACE.iterdir() if p.is_dir()}
    assert actual == CURRENT_AGENTS, (
        f"Workspace has {sorted(actual)} but CURRENT_AGENTS pins "
        f"{sorted(CURRENT_AGENTS)}. Update this test alongside workspace changes."
    )


# ── Round 22: shipped READMEs must also only invoke live agents ─────────────


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "doc_path",
    USER_FACING_DOCS,
    ids=lambda p: str(p.relative_to(REPO)),
)
def test_user_facing_docs_only_invoke_live_agents(doc_path):
    """Shipped READMEs and the demo runsheet all need valid --agent examples —
    they are the first code new users copy/paste."""
    assert doc_path.is_file(), f"expected user-facing doc missing: {doc_path}"
    text = doc_path.read_text(encoding="utf-8")
    invocations = _AGENT_INVOCATION.findall(text)
    stale = [name for name in invocations if name not in CURRENT_AGENTS]
    assert not stale, (
        f"{doc_path.relative_to(REPO)} invokes non-existent --agent "
        f"{set(stale)}. Live set is {sorted(CURRENT_AGENTS)}."
    )


@pytest.mark.parametrize(
    "doc_path",
    USER_FACING_DOCS,
    ids=lambda p: str(p.relative_to(REPO)),
)
def test_user_facing_docs_no_deleted_agent_references(doc_path):
    """Strict guard: deleted agent names cannot appear as ``--agent <name>``
    anywhere in user-facing docs, even in comments."""
    text = doc_path.read_text(encoding="utf-8")
    invocations = set(_AGENT_INVOCATION.findall(text))
    leaked = invocations & DELETED_AGENTS
    assert not leaked, (
        f"{doc_path.relative_to(REPO)} still invokes deleted agent(s) "
        f"{sorted(leaked)}. See Round 16-18 migrations."
    )
