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


# ────────────────────────────────────────────────────────────────────────────
# Contract 5: render_report is a TERMINAL tool (return_direct=True)
#
# Root cause being pinned (2026-05-12): on small models (gemma4 31b) the
# audit-runner flow produced the executive summary 2-3× in the user-facing
# reply. Each LLM layer (runner → orchestrator) paraphrased the previous
# layer's "verbatim echo" of render_report's return string.
#
# Fix: StructuredTool.from_function(render_report, return_direct=True) makes
# langgraph exit the agent loop right after the tool call — no second
# "format the response" LLM round-trip. If a future refactor drops this
# flag, the duplication regression returns silently.
# ────────────────────────────────────────────────────────────────────────────


def _load_render_report_module():
    """Load render_report.py without going through workspace tool discovery."""
    path = NETOPS_AUDIT / "runner" / "tools" / "render_report.py"
    assert path.exists(), f"render_report.py missing at {path}"
    spec = importlib.util.spec_from_file_location("_rr_contract_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_report_is_terminal_tool():
    """render_report's StructuredTool MUST have return_direct=True so
    langgraph exits the runner sub-agent loop after the call, preventing
    the small-model paraphrase-duplication regression."""
    mod = _load_render_report_module()
    tool = getattr(mod, "_render_report_tool", None)
    assert tool is not None, "_render_report_tool symbol disappeared"
    assert tool.return_direct is True, (
        "render_report lost return_direct=True — gemma4-class models will "
        "regress to 2-3× executive summary duplication. See "
        "dev_docs/00 (verbatim-passthrough fix, 2026-05-12)."
    )


def test_orchestrator_prompt_has_passthrough_rule():
    """Audit orchestrator must explicitly tell the LLM to forward
    sub-agent replies unchanged when they already contain a final
    artifact (Report saved: ... / Profile saved: ...)."""
    for tree in (NETOPS_AUDIT, PLATFORM_AUDIT):
        text = (tree / "prompts" / "orchestrator.md").read_text(encoding="utf-8")
        assert "passthrough" in text.lower(), (
            f"orchestrator.md in {tree} lost the passthrough rule — "
            "orchestrator will resume paraphrasing sub-agent replies."
        )
        assert "Report saved" in text and "Forward it to the user UNCHANGED" in text, (
            f"orchestrator.md in {tree} passthrough rule weakened — "
            "must name the artifact ('Report saved:') and the action "
            "('Forward it to the user UNCHANGED')."
        )


def test_audit_agent_md_declares_task_return_direct():
    """Audit orchestrator AGENT.md MUST set `task_return_direct: true`.

    Background: the prompt-level passthrough rule was not enough on small
    models (gemma4 31b kept paraphrasing sub-agent replies). The reliable
    fix is to mark the deepagents `task(...)` tool as terminal at compile
    time — done by reading this flag from AGENT.md frontmatter and setting
    a contextvars.ContextVar that the monkey-patched `_build_task_tool`
    consults. If the flag is dropped, orchestrator-layer paraphrase
    duplication of executive summaries returns silently."""
    for tree in (NETOPS_AUDIT, PLATFORM_AUDIT):
        text = (tree / "AGENT.md").read_text(encoding="utf-8")
        assert "task_return_direct: true" in text, (
            f"AGENT.md in {tree} lost `task_return_direct: true` — audit "
            "orchestrator will resume the second-LLM-round-trip paraphrase "
            "of sub-agent replies (executive summary duplicated on small "
            "models). See 2026-05-12 verbatim-passthrough fix."
        )


def test_agent_py_has_task_return_direct_monkeypatch():
    """The orchestrator-level `task_return_direct` flag is implemented by
    monkey-patching deepagents `_build_task_tool` at module import time
    in `src/olav/agents/agent.py`. If that patch disappears, AGENT.md's
    flag becomes a no-op and the gemma4 paraphrase duplication regresses."""
    agent_py = REPO_ROOT / "src" / "olav" / "agents" / "agent.py"
    src = agent_py.read_text(encoding="utf-8")
    assert "_TASK_RETURN_DIRECT" in src, (
        "Lost _TASK_RETURN_DIRECT contextvar in agent.py — the AGENT.md "
        "`task_return_direct: true` flag is now a no-op."
    )
    assert "_patched_build_task_tool" in src, (
        "Lost monkey-patch on deepagents._build_task_tool — task tool "
        "will be built with return_direct=False regardless of AGENT.md flag."
    )
    assert 'olav_config.get("task_return_direct")' in src, (
        "Lost the AGENT.md → contextvar bridge — flag won't propagate "
        "to the patched _build_task_tool."
    )


# ────────────────────────────────────────────────────────────────────────────
# Contract 6: CLI surfaces terminal-tool return values
#
# Without this, render_report's `return_direct=True` (Contract 5) is a
# regression — the report path + executive summary are captured in
# `_tool_results` but never reach the user terminal because the CLI's
# `on_chat_model_end` handler short-circuits once any streamed content
# lands in `_chunks`. Background: streaming=False on LLMFactory + a
# few intermediate LLM calls that DO emit `on_chat_model_stream` events
# leaves the final tool's return string stranded.
# ────────────────────────────────────────────────────────────────────────────


def test_cli_surfaces_terminal_tool_return_string():
    """The CLI streaming loop must extract `Report saved: <path>` from
    captured tool results and print it at end of run, even when other
    content was streamed earlier. Otherwise users running audit profiles
    on small models would see streamed per-section content but lose the
    report path + executive summary."""
    main_py = REPO_ROOT / "src" / "olav" / "cli" / "main.py"
    src = main_py.read_text(encoding="utf-8")
    assert "NL-CLI-TERMINAL-TOOL" in src, (
        "CLI's terminal-tool surfacing block disappeared — render_report's "
        "return string will not reach the user terminal when streaming "
        "captured intermediate content."
    )
    assert "Report saved:" in src and "_terminal_tool_lines" in src, (
        "CLI's terminal-tool block lost the path-extraction logic."
    )
    assert "📄" in src, (
        "CLI's terminal-tool surface lost its visual marker (📄) — "
        "users need a clear delimiter between streamed mid-run content "
        "and the final report path."
    )


# ────────────────────────────────────────────────────────────────────────────
# Contracts 7-9 (2026-05-12): production-readiness audit hardening.
# Three P1 fixes for the gaps surfaced after the in-vivo gemma4 audit-
# profile expansion: LLM evidence fabrication, missing freshness gate,
# silent finding-cap truncation. See dev_docs/00. issues.md:
#   * ISSUE-AUDIT-LLM-EVIDENCE-FABRICATION
#   * ISSUE-AUDIT-FRESHNESS-GATE-MISSING
#   * ISSUE-AUDIT-FINDINGS-CAP-SILENT-TRUNCATION
# ────────────────────────────────────────────────────────────────────────────


def test_correlation_pass_has_evidence_only_rules():
    """correlation_pass.md prompt MUST include the evidence-only hard
    rule block. Without it, gemma4 fabricates topology inferences
    ('shared physical path') from unrelated findings (e.g. multiple
    devices with Ethernet0/3 errors)."""
    for tree in (NETOPS_AUDIT, PLATFORM_AUDIT):
        text = (tree / "runner" / "prompts" / "correlation_pass.md").read_text(encoding="utf-8")
        assert "EVIDENCE-ONLY MODE" in text, (
            f"correlation_pass.md in {tree} lost EVIDENCE-ONLY MODE section — "
            "LLM will resume fabricating causal claims unsupported by SQL findings."
        )
        assert "FORBIDDEN" in text, (
            f"correlation_pass.md in {tree} lost the FORBIDDEN block listing "
            "specific hallucination patterns (causal claims, topology inferences)."
        )
        assert "shared physical path" in text or "shared infrastructure" in text, (
            f"correlation_pass.md in {tree} lost the explicit counter-example "
            "warning about 'shared physical path' fabrication — gemma4 made "
            "this exact mistake on interface_health prior to 2026-05-12 fix."
        )


def test_map_engine_has_freshness_gate():
    """map_engine MUST run the global freshness gate before returning audit
    JSON. Otherwise profiles without per-job freshness checks (e.g.
    ospf_health) silently report '✅ Healthy' on 11-day-old data."""
    me_py = NETOPS_AUDIT / "runner" / "tools" / "map_engine.py"
    src = me_py.read_text(encoding="utf-8")
    assert "freshness_warning" in src, (
        "map_engine lost freshness_warning field — global freshness gate "
        "is no longer emitted in audit JSON."
    )
    assert "freshness_threshold_hours" in src, (
        "map_engine lost freshness_threshold_hours profile knob — operators "
        "cannot override the 24h default."
    )
    assert "MAX(EXTRACT(EPOCH FROM (NOW() - last_seen))" in src, (
        "map_engine lost the SQL that computes max staleness from "
        "netops.devices.last_seen."
    )


def test_render_report_surfaces_freshness_and_truncation():
    """render_report MUST consume freshness_warning AND truncation flags
    from audit JSON. Two separate failure modes:
      (1) freshness: deterministic banner + LLM directive prevent
          '✅ Healthy' verdict on stale data.
      (2) truncation: section header warning when SQL produced more
          rows than max_findings allowed.
    """
    rr_py = NETOPS_AUDIT / "runner" / "tools" / "render_report.py"
    src = rr_py.read_text(encoding="utf-8")
    # P1.2 — freshness
    assert "freshness_warning" in src, (
        "render_report doesn't consume freshness_warning — stale-data "
        "banner won't be surfaced."
    )
    assert "STALE DATA — HARD CONSTRAINT" in src or "Stale Data Warning" in src, (
        "render_report freshness LLM directive lost — LLM can resume "
        "writing '✅ Healthy' on stale snapshots."
    )
    # P1.3 — truncation
    assert "truncated" in src and "shown_count" in src and "total_count" in src, (
        "render_report doesn't read truncation flags — silent 50-row "
        "cap regression returns."
    )
    assert "Results truncated" in src or "结果截断" in src, (
        "render_report lost the truncation header text — operators "
        "won't see 'showing N of TOTAL findings' warning."
    )


def test_execute_sql_job_returns_total_count_tuple():
    """_execute_sql_job MUST return (findings, total_count) tuple so the
    caller can detect + surface truncation. If this regresses to a flat
    list return, the silent-truncation regression returns."""
    import duckdb as _duckdb
    me_path = NETOPS_AUDIT / "runner" / "tools" / "map_engine.py"
    spec = importlib.util.spec_from_file_location("_me_contract_test", me_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    con = _duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE t (x INT)")
        con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(20)])
        result = mod._execute_sql_job(
            conn=con, query="SELECT x FROM t", window="1h", max_findings=5,
        )
        assert isinstance(result, tuple) and len(result) == 2, (
            "_execute_sql_job MUST return (findings, total) tuple. "
            "If it regresses to flat list, callers can no longer detect "
            "truncation and the silent-cap regression returns."
        )
        findings, total = result
        assert len(findings) == 5
        assert total == 20
    finally:
        con.close()


# ────────────────────────────────────────────────────────────────────────────
# Contracts 11–13 (2026-05-12): P2 production-readiness hardening.
#   * ISSUE-AUDIT-SCHEMA-DRIFT-NO-SELFTEST → selftest_profile() pin
#   * ISSUE-AUDIT-ERROR-COUNTERS-NO-BASELINE → INTERFACE_ERROR_DELTA pin
#   * ISSUE-AUDIT-NO-ALERTING-CHANNEL → webhook helper pin
# ────────────────────────────────────────────────────────────────────────────


def test_map_engine_has_selftest_profile():
    """map_engine MUST expose `selftest_profile(profile_path, db_path)`
    so operators can validate profile SQL against the live schema before
    running an audit. Loss of this function = schema drift goes silent."""
    me_py = NETOPS_AUDIT / "runner" / "tools" / "map_engine.py"
    src = me_py.read_text(encoding="utf-8")
    assert "def selftest_profile(" in src, (
        "map_engine.selftest_profile() disappeared — schema-drift detection "
        "regression. Profile SQL referencing renamed columns will silently "
        "return 0 rows and look like '✅ Healthy'."
    )
    assert "EXPLAIN" in src and "LIMIT 0" in src, (
        "selftest two-pass validation lost (EXPLAIN + LIMIT 0 probe). "
        "Column-name typos that EXPLAIN misses will leak through."
    )


def test_interface_health_uses_delta_not_absolute_counter():
    """interface_health profile MUST use delta-over-window for error
    counters, not absolute totals. Absolute counters yield false-positives
    on long-running devices (a 6-month device with 250 input_errors is
    normal). The job MUST also gracefully degrade to 0 findings when only
    1 snapshot exists (no LEFT JOIN false positives)."""
    profile = NETOPS_AUDIT / "profiles" / "interface_health.md"
    text = profile.read_text(encoding="utf-8")
    assert "INTERFACE_ERROR_DELTA" in text, (
        "interface_health lost INTERFACE_ERROR_DELTA job — regressed to "
        "absolute counter check. Long-running devices will be false-flagged."
    )
    assert "input_errors_delta" in text and "snap_pair" in text, (
        "Delta CTE structure lost — error counters back to absolute."
    )
    assert "p.snapshot_id IS NULL" in text or "p.snapshot_id IS NOT NULL" in text, (
        "Single-snapshot guard lost — query will emit false positives when "
        "no baseline snapshot exists."
    )


def test_render_report_has_alert_webhook_helper():
    """render_report MUST expose `_post_critical_alert` that POSTs to
    OLAV_ALERT_WEBHOOK_URL on Critical findings. Loss of this helper means
    weekend critical events never page anyone."""
    rr_py = NETOPS_AUDIT / "runner" / "tools" / "render_report.py"
    src = rr_py.read_text(encoding="utf-8")
    assert "def _post_critical_alert(" in src, (
        "_post_critical_alert helper disappeared — audit Critical findings "
        "will only write .md, no external notification path."
    )
    assert "OLAV_ALERT_WEBHOOK_URL" in src, (
        "OLAV_ALERT_WEBHOOK_URL env var lookup lost from render_report — "
        "alerting helper has no way to be configured."
    )
    assert "best-effort" in src.lower() or "swallow" in src.lower() or "must not raise" in src.lower() or "NOT raised" in src, (
        "Lost the 'webhook is best-effort' contract — a 5xx receiver could "
        "now break the audit pipeline."
    )
