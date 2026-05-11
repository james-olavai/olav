"""Audit architecture contract tests (rev 258).

Three concrete contracts pinned here, each addressing a real bug class:

  1. **No Designer-routing instructions** — the `designer` sub-agent
     was merged into `auditor` in Round 17 but two orchestrator prompt
     files (`audit/prompts/orchestrator.md` + `audit/prompts/system.md`)
     still issued "Route to Designer sub-agent" instructions through
     rev 257. LLM-side: the orchestrator would emit
     `task("designer", ...)` calls that hit a nonexistent sub-agent.

  2. **No broken Job-field teaching in author-side prompts** — the
     "Profile Job Field Specification" block in
     `audit/auditor/prompts/system.md` listed `duckdb_query /
     warning_threshold / critical_threshold / operator` fields that
     did NOT match the canonical schema (`type / severity / query /
     section_prompt`) actually read by `map_engine`. Was the same
     schema-drift bug fixed in rev 257 on append_jobs.

  3. **Pydantic schemas cover what map_engine reads** — the
     authoritative truth is the Pydantic `ProfileJob` model. Any
     field that `map_engine.run_map_engine` reads via
     `job.get("X")` must be a declared model field; otherwise a
     Pydantic-typed save_profile call can produce a job that
     silently misses fields when the engine reads them back.

  4. **Mirror drift between olav-netops and root workspace** —
     three copies coexist (olav-netops source / root mirror /
     demo7 deploy). Phase 1 + Phase E both got bitten by drift.
     This test diff-checks that olav-netops (source-of-truth) and
     root .olav/workspace/ agree on the prompt files we just
     unified.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path.cwd()
NETOPS_AUDIT = REPO_ROOT / "olav-netops/.olav/workspace/audit"
PLATFORM_AUDIT = REPO_ROOT / ".olav/workspace/audit"

# Files that must stay byte-for-byte in sync across the two trees.
# These are documents — Python tools also exist but their drift was
# fixed in Phase E and is harder to enforce here without a sync gate.
MIRRORED_PROMPT_PATHS = [
    "prompts/orchestrator.md",
    "prompts/system.md",
    "AGENT.md",
    # rev 259: Run/Author/Curator split — three sub-agent SKILL.md +
    # their system prompts. The retired `auditor/` directory is no
    # longer a sub-agent and is kept only as `_legacy_auditor/` in
    # olav-netops (backup, not mirrored).
    "runner/SKILL.md",
    "runner/prompts/system.md",
    "author/SKILL.md",
    "author/prompts/system.md",
    "curator/SKILL.md",
]


# ─────────────────────────────────────────────────────────────────────
# 1. No Designer-routing instructions in active orchestrator prompts
# ─────────────────────────────────────────────────────────────────────


# Historical references are OK ("merged from … designer", "designer was
# merged into auditor in Round 17") — those tell the reader the history.
# What is NOT ok is an active instruction like "Route to Designer".
_ACTIVE_DESIGNER_INSTRUCTION_RE = re.compile(
    r"""(?ix)
    (
        route \s+ to \s+ (?:the\s+)? designer
      | task\s*\(\s*['"]designer['"]
      | delegate \s+ to \s+ designer
      | pass[^\n]{0,40} to \s+ designer
    )
    """
)


@pytest.mark.parametrize(
    "rel_path",
    [
        "prompts/orchestrator.md",
        "prompts/system.md",
    ],
)
@pytest.mark.parametrize("root", [NETOPS_AUDIT, PLATFORM_AUDIT])
def test_no_active_designer_routing_in_orchestrator_prompts(rel_path, root):
    p = root / rel_path
    if not p.exists():
        pytest.skip(f"{p} not present in this tree")
    text = p.read_text(encoding="utf-8")
    match = _ACTIVE_DESIGNER_INSTRUCTION_RE.search(text)
    assert match is None, (
        f"{p} still contains active Designer-routing instruction: "
        f"{match.group(0)!r}. Designer was merged into auditor in "
        f"Round 17; route to Auditor (Profile Authoring mode) instead."
    )


# ─────────────────────────────────────────────────────────────────────
# 2. No broken Job-field teaching in author-side prompts
# ─────────────────────────────────────────────────────────────────────


# These field names were the rev 257 schema drift: they appeared in
# append_jobs.AppendProfileJob + the auditor system prompt, but
# map_engine actually reads `type / severity / query / section_prompt`.
# Any LLM training off these tokens would produce broken profiles.
_BROKEN_JOB_FIELDS = (
    "duckdb_query",
    "warning_threshold",
    "critical_threshold",
)


@pytest.mark.parametrize("root", [NETOPS_AUDIT, PLATFORM_AUDIT])
@pytest.mark.parametrize("rel", ["author/prompts/system.md", "author/SKILL.md"])
def test_author_prompts_do_not_teach_broken_schema(root, rel):
    """rev 259 Run/Author split: the author sub-agent owns Profile
    authoring. Its system prompt + SKILL.md must not regurgitate the
    historical broken field set."""
    p = root / rel
    if not p.exists():
        pytest.skip(f"{p} not present in this tree")
    text = p.read_text(encoding="utf-8")
    leaked = [f for f in _BROKEN_JOB_FIELDS if f in text]
    assert not leaked, (
        f"{p} still mentions broken Job fields {leaked!r}. "
        f"Canonical schema = name/type/severity/section_prompt/query "
        f"(see save_profile.ProfileJob). The Pydantic schema is the "
        f"authoritative spec; drop the field list."
    )


# ─────────────────────────────────────────────────────────────────────
# 3. Pydantic schemas cover what map_engine reads
# ─────────────────────────────────────────────────────────────────────


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# Fields map_engine.run_map_engine reads off each job dict (as
# `job.get("X", ...)`). Drift here means a Pydantic-typed save_profile
# can omit a field that the reader expects.
_MAP_ENGINE_READS = {
    "name",
    "type",
    "severity",
    "section_prompt",
    "query",
    "semantic_query",
    "threshold",
}


def test_map_engine_reads_only_declared_pydantic_fields():
    """ProfileJob must declare every field map_engine reads via
    .get(). Otherwise a typed save_profile() call produces a job dict
    that the engine reads as missing, silently returning zero
    findings."""
    sp = _load_module(
        "_sp_contract",
        NETOPS_AUDIT / "author/tools/save_profile.py",
    )
    declared = set(sp.ProfileJob.model_fields.keys())
    missing = _MAP_ENGINE_READS - declared
    assert not missing, (
        f"ProfileJob is missing fields that map_engine reads: "
        f"{missing!r}. Either add them to ProfileJob or remove the "
        f"reader."
    )


def test_append_profile_job_field_set_mirrors_save_profile_job():
    """Both author-side tools must declare the same canonical schema.
    This is the rev 256→257 regression that bit Designer-flow with
    zero findings. The schemas are duplicated in code (no shared
    module — dynamic tool loading constraint), so a test pins the
    mirror invariant."""
    sp = _load_module(
        "_sp_contract2",
        NETOPS_AUDIT / "author/tools/save_profile.py",
    )
    aj = _load_module(
        "_aj_contract2",
        NETOPS_AUDIT / "author/tools/append_jobs.py",
    )
    sf = set(sp.ProfileJob.model_fields.keys())
    af = set(aj.AppendProfileJob.model_fields.keys())
    assert sf == af, (
        f"save_profile.ProfileJob and append_jobs.AppendProfileJob "
        f"have drifted: only_in_save={sf - af}, only_in_append={af - sf}"
    )


# ─────────────────────────────────────────────────────────────────────
# 4. Mirror drift between olav-netops source and root .olav/workspace
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rel_path", MIRRORED_PROMPT_PATHS)
def test_audit_workspace_mirrors_stay_in_sync(rel_path):
    """olav-netops/ is the source-of-truth (workspace.yaml `source:`
    points there). Root .olav/workspace/audit/ is the platform-side
    mirror that some tooling reads (e.g. olav explain).

    These six text files have triggered drift bugs in this session:
      - auditor/SKILL.md (path:dict format bug — Phase 1)
      - curator/SKILL.md (tools: null vs explicit list — Phase 1)
      - auditor/prompts/system.md (Job field teaching — Phase 1+rev258)
      - prompts/orchestrator.md (Designer routing — rev 258)
      - prompts/system.md (Designer routing — rev 258)
      - AGENT.md (subagents list — guarded for safety)

    Any future fix must update BOTH trees. This test catches drift on
    next run.
    """
    netops_path = NETOPS_AUDIT / rel_path
    root_path = PLATFORM_AUDIT / rel_path
    if not netops_path.exists() or not root_path.exists():
        pytest.skip(f"file missing in one tree: {rel_path}")
    netops_text = netops_path.read_text(encoding="utf-8")
    root_text = root_path.read_text(encoding="utf-8")
    assert netops_text == root_text, (
        f"{rel_path} drifted between olav-netops and root .olav/workspace.\n"
        f"  source : {netops_path}\n"
        f"  mirror : {root_path}\n"
        f"Run: cp {netops_path} {root_path}\n"
        f"(olav-netops is the source-of-truth per workspace.yaml)."
    )
