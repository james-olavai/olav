"""Sub-agent reachability + prompt self-consistency gate (dev_docs/97 §test-strategy).

This is the deterministic, zero-LLM gate that would have caught the db-query /
api-query class of bug (an agent whose only tool is ``execute_skill_script`` but
whose prompt never told the model its own ``skill_name`` → 0/76 correct calls,
total failure, invisible to every existing test because:
  - the *script* worked in isolation (unit tests green),
  - the *structure* was valid (scripts: + execute_skill_script declared),
  - the sub-agent was never exercised through a real delegation with a model.

Three checks, all over the AUTHORITATIVE workspace sources (not the .olav
runtime mirror, which workspace_drift_gate keeps in sync):

  A. Recipe self-consistency — a script-bearing sub-agent that can call scripts
     (execute_skill_script in tools:) must get the exact call shape with ITS OWN
     skill_name injected into its prompt (via agent._inject_script_recipe).
  B. No dangling subagents: refs — every declared ``subagents:`` path resolves.
  C. No orphan sub-agents — every sub-agent dir is declared by some parent
     (or is a known auto-discovered skill).
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from olav.agents.agent import _inject_script_recipe

REPO = Path(__file__).resolve().parents[2]
WORKSPACE_ROOTS = [
    REPO / "src" / "olav" / "data" / "workspace",       # platform authoritative
    REPO / "olav-netops" / ".olav" / "workspace",       # netops/audit authoritative
    REPO / "olav-presales" / ".olav" / "workspace",     # presales authoritative
    # olav-ent authoritative. Added 2026-08-03: without it the enterprise lab
    # skill was invisible to every check here — it sat undeclared under
    # netops/ for as long as it existed and no gate said so, which is the
    # exact rot this file was written to catch.
    #
    # Moved 2026-08-04 from the repo root into the package, where it is now a
    # real bundled skillpack (dev_docs/114 §11). Watch the collected-test count
    # if this path ever changes again: the move silently dropped this root and
    # the gate went from 1208 to 1207 tests with nothing failing.
    REPO / "olav-ent" / "src" / "olav" / "enterprise" / "data" / "skillpack" / "workspace",
]

# Auto-discovered skills that are NOT delegated subagents (loaded via
# SkillsMiddleware, not declared in any parent's subagents: list).
# `lab` is the enterprise clab digital-twin skill. It is deliberately NOT
# declared in any `subagents:` list: it installs under the platform `services`
# agent, whose SkillsMiddleware discovers sub-skill directories on its own, and
# a static declaration in a PUBLIC SKILL.md pointing at an enterprise-only
# directory would dangle on every OSS install (check B above).
# Imported, not restated: this list lived as a literal here, in `olav doctor`
# and in agent.py, and the copies had already diverged.
from olav.agents.agent import AUTODISCOVERED_SKILLS as _AUTODISCOVERED


def _all_skill_mds() -> list[tuple[Path, Path]]:
    """(root, skill_md_path) for every SKILL.md under the authoritative roots."""
    out = []
    for root in WORKSPACE_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("SKILL.md"):
            out.append((root, p))
    return out


def _is_subagent(root: Path, skill_md: Path) -> bool:
    """A sub-agent lives at <root>/<domain>/<sub>/SKILL.md (depth 2)."""
    return len(skill_md.relative_to(root).parts) == 3


def _tool_names(meta: dict) -> set[str]:
    tools = meta.get("tools") or []
    return {(t if isinstance(t, str) else t.get("name", "")) for t in tools}


def _subagent_cases():
    cases = []
    for root, p in _all_skill_mds():
        if not _is_subagent(root, p):
            continue
        rel = p.relative_to(root)
        cases.append(pytest.param(root, p, id="/".join(rel.parts[:-1])))
    return cases


# ── Check A: recipe self-consistency (the db-query / api-query guard) ────────

@pytest.mark.parametrize("root,skill_md", _subagent_cases())
def test_script_bearing_subagent_gets_recipe_with_own_skill_name(root, skill_md):
    fm = frontmatter.load(str(skill_md))
    meta = fm.metadata or {}
    name = meta.get("name") or skill_md.parent.name
    scripts = meta.get("scripts") or []
    if "execute_skill_script" not in _tool_names(meta) or not scripts:
        pytest.skip("not a script-bearing LLM-callable sub-agent")

    recipe = _inject_script_recipe(fm.content or "", name, meta)
    # the model must be told to pass THIS agent's own skill_name
    assert f'execute_skill_script(skill_name="{name}"' in recipe, (
        f"{name}: prompt lacks the execute_skill_script recipe with its own "
        f"skill_name — a small model will guess it (db-query/api-query class). "
        f"agent._inject_script_recipe must fire for this agent."
    )
    # and every declared script file must be named in the recipe
    for s in scripts:
        if not isinstance(s, dict):
            continue
        fname = s.get("file") or (f"{s.get('name')}.py" if s.get("name") else None)
        if fname:
            assert fname in recipe, f"{name}: script {fname!r} missing from injected recipe"


# ── Check B: declared subagents: paths resolve ───────────────────────────────

def test_declared_subagents_resolve():
    runtime = REPO / ".olav" / "workspace"  # merged deployment: all domains co-located
    dangling = []
    for root, p in _all_skill_mds():
        meta = frontmatter.load(str(p)).metadata or {}
        for sp in meta.get("subagents") or []:
            rel = sp.get("path") if isinstance(sp, dict) else sp
            if not rel:
                continue
            # (1) resolve in the authoritative package (within-domain refs)
            if (p.parent / rel).resolve().is_file():
                continue
            # (2) cross-package borrow (e.g. netops → ../core/writer): the ref
            #     resolves in the merged runtime mirror where every domain is
            #     co-deployed side-by-side.
            runtime_decl = runtime / p.relative_to(root)
            if (runtime_decl.parent / rel).resolve().is_file():
                continue
            dangling.append(f"{p.relative_to(root)} → {rel}")
    assert not dangling, "dangling subagents: refs (point at missing SKILL.md):\n" + "\n".join(dangling)


# ── Check C: no orphan sub-agents (declared by a parent, or auto-discovered) ─

def test_no_orphan_subagents():
    declared: set[str] = set()
    for _root, p in _all_skill_mds():
        meta = frontmatter.load(str(p)).metadata or {}
        for sp in meta.get("subagents") or []:
            rel = sp.get("path") if isinstance(sp, dict) else sp
            if rel:
                # final dir name of the declared path
                declared.add(Path(rel).parent.name)
    orphans = []
    for root, p in _all_skill_mds():
        if not _is_subagent(root, p):
            continue
        dirname = p.parent.name
        if dirname not in declared and dirname not in _AUTODISCOVERED:
            orphans.append(str(p.relative_to(root)))
    assert not orphans, (
        "orphan sub-agent dirs (not declared by any parent's subagents: and "
        "not a known auto-discovered skill — they rot invisibly, like db-query):\n"
        + "\n".join(orphans)
    )


# ── Check D: an "auto-discovered" skill is actually discoverable ─────────────
#
# The allowlist above is the one place this file trusts a claim instead of
# checking one. `SkillsMiddleware` only scans the *direct children* of a
# top-level agent directory (agent.py: `has_sub_skills`), so a skill nested any
# deeper is discovered by nobody and is an orphan wearing a waiver — the exact
# rot the orphan check exists to prevent, now with a note excusing it.

def test_autodiscovered_skills_are_where_the_middleware_looks():
    misplaced = []
    for root, p in _all_skill_mds():
        if p.parent.name not in _AUTODISCOVERED:
            continue
        rel = p.relative_to(root).parts
        # <top-level agent>/<skill>/SKILL.md — exactly two path segments
        if len(rel) != 3:
            misplaced.append(f"{'/'.join(rel)} (depth {len(rel) - 1})")
            continue
        # The parent agent may live in a DIFFERENT root: an enterprise unit
        # ships `services/lab` while the `services` agent itself is platform.
        # Install merges the trees, so the question is whether *some* root
        # provides the top-level agent this skill lands under.
        if not any((r / rel[0] / "SKILL.md").is_file() for r in WORKSPACE_ROOTS):
            misplaced.append(
                f"{'/'.join(rel)} (no root provides a '{rel[0]}' top-level agent)")
    assert not misplaced, (
        "these skills are waived as auto-discovered but SkillsMiddleware "
        "scans only the direct children of a top-level agent dir, so nothing "
        "will find them:\n  " + "\n  ".join(misplaced)
    )
