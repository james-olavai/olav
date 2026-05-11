"""Tests for audit Designer structured-output tools (Phase E / Task #301).

Covers two LangChain ``StructuredTool``s that drive the audit Profile
authoring flow:

  * ``save_profile``  (create / replace a Profile from typed jobs)
  * ``append_jobs``   (extend an existing Profile with typed jobs)

Both must produce a single canonical YAML schema (``name / type /
severity / section_prompt / query | semantic_query / threshold``) so
``map_engine`` reads either entry-point's output identically. The
schema-mirror invariant was broken from rev 0 → rev 256: append_jobs
declared ``duckdb_query / warning_threshold / critical_threshold /
operator`` which never matched what map_engine reads, so any profile
produced by append_jobs would silently return zero findings. Rev 257
aligned both schemas; these tests pin the invariant.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(
    "olav-netops/.olav/workspace/audit/author/tools"
)


def _import_module_from_path(modname: str, file_path: Path):
    """Load a module from an explicit .py path (workspace tools aren't
    on sys.path by default in the test runner)."""
    spec = importlib.util.spec_from_file_location(modname, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def save_profile_mod():
    mod = _import_module_from_path(
        "_save_profile_test",
        Path.cwd() / WORKSPACE / "save_profile.py",
    )
    return mod


@pytest.fixture
def append_jobs_mod(monkeypatch):
    # append_jobs imports `read_profile` via dynamic path — register
    # the actual workspace helper under the bare module name so the
    # runtime ``from read_profile import read_profile`` resolves.
    # The runtime helper sibling lives under tools/ in olav-netops, under
    # scripts/ in the platform mirror — locate whichever exists.
    repo_root = Path.cwd()
    candidates = [
        repo_root / "olav-netops/.olav/workspace/audit/author/tools/read_profile.py",
        repo_root / ".olav/workspace/audit/author/tools/read_profile.py",
    ]
    rp_path = next((p for p in candidates if p.exists()), None)
    if rp_path is None:
        pytest.skip("read_profile.py not found in either workspace location")
    sys.path.insert(0, str(rp_path.parent))
    rp_mod = _import_module_from_path("read_profile", rp_path)
    sys.modules["read_profile"] = rp_mod
    mod = _import_module_from_path(
        "_append_jobs_test",
        Path.cwd() / WORKSPACE / "append_jobs.py",
    )
    yield mod
    # Cleanup
    sys.path.pop(0)
    sys.modules.pop("read_profile", None)


# ─────────────────────────────────────────────────────────────────────
# 1. Schema invariant — append_jobs.AppendProfileJob mirrors save_profile.ProfileJob
# ─────────────────────────────────────────────────────────────────────


def test_authoring_schemas_share_canonical_field_set(save_profile_mod, append_jobs_mod):
    """The two Pydantic Job models must declare the same canonical
    field set. Drift here means map_engine reads one shape but the
    other tool produces a different one — that was rev 256's silent
    false-green bug."""
    save_fields = set(save_profile_mod.ProfileJob.model_fields.keys())
    append_fields = set(append_jobs_mod.AppendProfileJob.model_fields.keys())
    assert save_fields == append_fields, (
        f"save_profile.ProfileJob and append_jobs.AppendProfileJob have "
        f"drifted: save_only={save_fields - append_fields}, "
        f"append_only={append_fields - save_fields}"
    )


def test_authoring_schemas_carry_map_engine_required_fields(save_profile_mod):
    """map_engine reads job.get('type') / .get('severity') /
    .get('query') / .get('section_prompt'). The schema must surface
    them as declared Pydantic fields."""
    required = {"name", "type", "severity", "section_prompt", "query"}
    assert required <= set(save_profile_mod.ProfileJob.model_fields.keys())


# ─────────────────────────────────────────────────────────────────────
# 2. Round-trip — save_profile → read_profile → append_jobs preserves jobs
# ─────────────────────────────────────────────────────────────────────


def test_save_profile_writes_canonical_yaml(save_profile_mod, tmp_path):
    job = save_profile_mod.ProfileJob(
        name="IFACE_DOWN",
        type="sql",
        severity="Critical",
        section_prompt="List down interfaces.",
        query="SELECT device_name, interface FROM interfaces WHERE status='down'",
    )
    out = save_profile_mod._save_profile_validated(
        name="rt_test",
        yaml_jobs=[job],
        markdown_body="Round-trip test profile.",
        profiles_dir=str(tmp_path),
    )
    written = Path(out)
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    # Must use canonical field names — not duckdb_query / warning_threshold
    assert "type: sql" in text
    assert "severity: Critical" in text
    assert "section_prompt" in text
    assert "query:" in text


def test_round_trip_save_then_append(save_profile_mod, append_jobs_mod, tmp_path):
    # Create initial profile with one job
    j1 = save_profile_mod.ProfileJob(
        name="JOB_ONE",
        type="sql",
        severity="Warning",
        section_prompt="Check 1",
        query="SELECT 1 AS device, 1 AS metric_value",
    )
    save_profile_mod._save_profile_validated(
        name="rt_two",
        yaml_jobs=[j1],
        markdown_body="initial",
        profiles_dir=str(tmp_path),
    )

    # Append a second job using append_jobs
    j2 = append_jobs_mod.AppendProfileJob(
        name="JOB_TWO",
        type="sql",
        severity="Critical",
        section_prompt="Check 2",
        query="SELECT 2 AS device, 2 AS metric_value",
    )
    result = append_jobs_mod.append_jobs(
        profile_name="rt_two",
        new_jobs=[j2],
        profiles_dir=str(tmp_path),
    )
    assert "ERROR" not in result
    assert "JOB_TWO" in result

    # Verify the merged file has both jobs in canonical form
    merged = (tmp_path / "rt_two.md").read_text(encoding="utf-8")
    assert "JOB_ONE" in merged and "JOB_TWO" in merged
    assert merged.count("type: sql") == 2
    assert merged.count("section_prompt") >= 2


def test_append_jobs_blocks_duplicate_name(save_profile_mod, append_jobs_mod, tmp_path):
    j1 = save_profile_mod.ProfileJob(
        name="DUP_NAME",
        type="sql",
        severity="Info",
        section_prompt="P1",
        query="SELECT 1",
    )
    save_profile_mod._save_profile_validated(
        name="dup_test",
        yaml_jobs=[j1],
        markdown_body="",
        profiles_dir=str(tmp_path),
    )

    j_dup = append_jobs_mod.AppendProfileJob(
        name="DUP_NAME",  # same name → must be rejected
        type="sql",
        severity="Critical",
        section_prompt="P2",
        query="SELECT 2",
    )
    result = append_jobs_mod.append_jobs(
        profile_name="dup_test",
        new_jobs=[j_dup],
        profiles_dir=str(tmp_path),
    )
    assert result.startswith("ERROR")
    assert "DUP_NAME" in result


def test_append_jobs_rejects_sql_without_query(append_jobs_mod, save_profile_mod, tmp_path):
    """Pydantic accepts query=None for type=sql (because semantic_query
    is also Optional), so the SQL/LanceDB branch invariant is enforced
    inside append_jobs.

    Create a base profile so read_profile succeeds, then attempt to
    append a malformed job.
    """
    base = save_profile_mod.ProfileJob(
        name="BASE",
        type="sql",
        severity="Info",
        section_prompt="base",
        query="SELECT 1",
    )
    save_profile_mod._save_profile_validated(
        name="branch_test",
        yaml_jobs=[base],
        markdown_body="",
        profiles_dir=str(tmp_path),
    )

    bad = append_jobs_mod.AppendProfileJob(
        name="NO_QUERY",
        type="sql",
        severity="Critical",
        section_prompt="oops",
        # query intentionally omitted
    )
    result = append_jobs_mod.append_jobs(
        profile_name="branch_test",
        new_jobs=[bad],
        profiles_dir=str(tmp_path),
    )
    assert result.startswith("ERROR")
    assert "type='sql'" in result and "query" in result


# ─────────────────────────────────────────────────────────────────────
# 3. read_profile now surfaces full body + frontmatter flags
# ─────────────────────────────────────────────────────────────────────


def test_read_profile_returns_full_body_and_flags(tmp_path):
    """append_jobs needs read_profile to return the entire markdown
    body + persist_findings_to_db / max_findings_per_job — not just
    body_preview — so it can preserve them on rewrite."""
    from olav.core.auditor.profile_read import read_profile

    p = tmp_path / "with_body.md"
    body = "## Narrative\n\nDetailed explanation about what this profile audits, "
    body += "which is well over the 300-char body_preview cap so we can "
    body += "distinguish the full-body path. " * 12
    p.write_text(
        f"""---
name: with_body
version: '4.0'
persist_findings_to_db: true
max_findings_per_job: 25
jobs:
- name: J1
  type: sql
  severity: Info
  section_prompt: test
  query: SELECT 1
---

{body}
""",
        encoding="utf-8",
    )
    parsed = read_profile("with_body", str(tmp_path))
    assert "body" in parsed
    assert len(parsed["body"]) > 300
    assert "Narrative" in parsed["body"]
    assert parsed["persist_findings_to_db"] is True
    assert parsed["max_findings_per_job"] == 25
