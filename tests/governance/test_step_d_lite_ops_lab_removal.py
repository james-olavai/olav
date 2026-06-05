"""Sprint 3 Step D lite — ops-lab/ shell removed, content merged into ops/lab/ (round 18).

v0.18.1 removes the transitional ``.olav/workspace/ops-lab/`` top-level
directory. All 10 tools in that shell were symlinks into
``ops/lab/tools/``; unique CAB knowledge from ``ops-lab/SKILL.md`` and
``ops-lab/SKILL.md`` is merged into ``ops/lab/SKILL.md``.

Guards:

* ``.olav/workspace/ops-lab/`` must not exist.
* ``ops/lab/SKILL.md`` advertises the merged "Verified Working Patterns"
  and "Multi-Node Topology Adaptation" sections.
* ``src/README_ZH.md`` no longer shows ``--agent ops-lab`` as a CLI example.
* ``src/olav/agents/agent.py`` docstring references ``ops/lab`` (not the
  deleted ``ops-lab``).
* ``src/olav/platform/execution/{ssh,base,local}.py`` docstrings likewise
  no longer reference the deleted directory.
* ``PLATFORM.md`` lists exactly the canonical v0.18.1 agent set.
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"


def test_ops_lab_top_level_removed():
    assert not (WORKSPACE / "ops-lab").exists(), (
        "top-level ops-lab/ must be deleted after Step D lite merge"
    )


def test_ops_lab_subagent_still_present():
    """Post-dev_docs/85: ops/lab/ was removed; lab is no longer a sub-agent."""
    assert not (WORKSPACE / "ops" / "lab").exists(), (
        "ops/lab/ should be gone — lab sub-agent was removed in dev_docs/85"
    )
    assert not (WORKSPACE / "netops" / "lab").exists(), (
        "netops/lab/ should not exist — lab is no longer a dedicated sub-agent"
    )


def test_ops_lab_skill_md_carries_merged_sections():
    """Post-dev_docs/85: ops/lab no longer exists; skip this content check."""
    assert not (WORKSPACE / "ops" / "lab").exists(), (
        "ops/lab/ removed in dev_docs/85 — no SKILL.md to check"
    )


def test_readme_zh_no_longer_advertises_ops_lab_agent():
    text = (REPO / "src" / "README_ZH.md").read_text(encoding="utf-8")
    assert "--agent ops-lab" not in text, (
        "README_ZH.md still advertises '--agent ops-lab'; update to "
        "'--agent ops' so the orchestrator delegates via task('ops-lab')"
    )


def test_agent_py_docstring_uses_ops_lab_subpath():
    text = (REPO / "src" / "olav" / "agents" / "agent.py").read_text(encoding="utf-8")
    # Forbidden: bare 'ops-lab' with hyphen in code comments
    # Allowed: 'ops/lab' (sub-agent path)
    bad_lines = [
        line for line in text.splitlines()
        if "ops-lab" in line and "ops/lab" not in line
    ]
    assert not bad_lines, (
        f"src/olav/agents/agent.py still references deleted 'ops-lab':\n"
        + "\n".join(bad_lines)
    )


def test_execution_backend_docstrings_updated():
    for fname in ("ssh.py", "base.py", "local.py"):
        p = REPO / "src" / "olav" / "platform" / "execution" / fname
        text = p.read_text(encoding="utf-8")
        bad = [l for l in text.splitlines() if "ops-lab" in l and "ops/lab" not in l]
        assert not bad, (
            f"{p} still references deleted 'ops-lab':\n" + "\n".join(bad)
        )


def test_core_agent_md_escalation_hint_updated():
    """Round 19 follow-up — core/SKILL.md escalation hint must not suggest
    the deleted `--agent ops-lab` CLI path.
    """
    text = (WORKSPACE / "core" / "SKILL.md").read_text(encoding="utf-8")
    # The deleted CLI path `--agent ops-lab` must be gone entirely.
    assert "--agent ops-lab" not in text, (
        "core/SKILL.md still advertises the deleted `--agent ops-lab` path. "
        "Reword to `--agent ops \"<CAB task>\"` so the ops orchestrator "
        "delegates to the ops/lab sub-agent."
    )


def test_platform_md_lists_canonical_four_agents():
    """Post-dev_docs/85: PLATFORM.md reflects the new canonical agent set."""
    platform_md = WORKSPACE / "olav.md"
    text = platform_md.read_text(encoding="utf-8")
    assert text.startswith("---")
    meta = yaml.safe_load(text.split("---", 2)[1]) or {}
    agents = set(meta.get("agents", []))
    expected = {"admin", "audit", "core", "devops", "netops", "services"}  # ADR-0014: + platform services agent
    assert agents == expected, (
        f"olav.md agents list {sorted(agents)} != canonical "
        f"{sorted(expected)}. Run `olav refresh`."
    )
