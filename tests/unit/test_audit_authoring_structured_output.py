"""Tests for audit Profile authoring tools (Phase E / Task #301).

Covers ``write_profile`` — the merged create + append entry point that
replaced the former ``save_profile`` + ``append_jobs`` pair (rev ~303).

Both modes produce the same canonical YAML schema so map_engine reads
either mode's output identically.  The schema-mirror invariant was broken
from rev 0 → rev 256; rev 257 aligned both schemas; rev ~303 merged them
into a single ``ProfileJob`` class.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(
    "olav-netops/.olav/workspace/audit/audit-author/scripts"
)


def _import_module_from_path(modname: str, file_path: Path):
    """Load a module from an explicit .py path."""
    spec = importlib.util.spec_from_file_location(modname, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def wp_mod():
    """Load write_profile.py (merged create+append entrypoint)."""
    return _import_module_from_path(
        "_write_profile_test",
        Path.cwd() / WORKSPACE / "write_profile.py",
    )


# ─────────────────────────────────────────────────────────────────────
# 1. Schema invariant — single ProfileJob has canonical map_engine fields
# ─────────────────────────────────────────────────────────────────────


def test_profile_job_has_canonical_field_set(wp_mod):
    """ProfileJob must declare the canonical schema fields that map_engine reads."""
    required = {"name", "type", "severity", "section_prompt", "query", "semantic_query"}
    actual = set(wp_mod.ProfileJob.model_fields.keys())
    assert required <= actual, f"ProfileJob missing fields: {required - actual}"


def test_profile_job_carries_map_engine_required_fields(wp_mod):
    """map_engine reads job.get('type') / .get('severity') / .get('query') /
    .get('section_prompt'). ProfileJob must declare all four."""
    required = {"name", "type", "severity", "section_prompt", "query"}
    assert required <= set(wp_mod.ProfileJob.model_fields.keys())


# ─────────────────────────────────────────────────────────────────────
# 2. mode="create" — write canonical YAML
# ─────────────────────────────────────────────────────────────────────


def test_write_profile_create_writes_canonical_yaml(wp_mod, tmp_path):
    job = wp_mod.ProfileJob(
        name="IFACE_DOWN",
        type="sql",
        severity="Critical",
        section_prompt="List down interfaces.",
        query="SELECT device_name FROM interfaces WHERE status='down'",
    )
    out = wp_mod._save_profile_validated(
        name="rt_test",
        yaml_jobs=[job],
        markdown_body="Round-trip test profile.",
        profiles_dir=str(tmp_path),
    )
    # Return may include a selftest warning after the first line — extract just the path.
    written = Path(out.split("\n")[0].strip())
    assert written.exists(), f"Profile not written: {out}"
    text = written.read_text(encoding="utf-8")
    assert "type: sql" in text
    assert "severity: Critical" in text
    assert "section_prompt" in text
    assert "query:" in text
    assert "duckdb_query" not in text
    assert "warning_threshold" not in text


def test_write_profile_create_mode(wp_mod, tmp_path):
    result = wp_mod.write_profile(
        name="direct_create",
        jobs=[{
            "name": "JOB_A",
            "type": "sql",
            "severity": "Warning",
            "section_prompt": "Check A",
            "query": "SELECT 1 AS device, 1 AS metric_value, 'x' AS metric_name, 'ok' AS severity_hint",
        }],
        mode="create",
        markdown_body="created directly",
        profiles_dir=str(tmp_path),
    )
    assert "ERROR" not in result
    assert (tmp_path / "direct_create.md").exists()


# ─────────────────────────────────────────────────────────────────────
# 3. mode="append" — round-trip and validation
# ─────────────────────────────────────────────────────────────────────


def test_round_trip_create_then_append(wp_mod, tmp_path):
    wp_mod.write_profile(
        name="rt_two",
        jobs=[{
            "name": "JOB_ONE",
            "type": "sql",
            "severity": "Warning",
            "section_prompt": "Check 1",
            "query": "SELECT 1 AS device, 1 AS metric_value, 'x' AS metric_name, 'ok' AS severity_hint",
        }],
        mode="create",
        markdown_body="initial",
        profiles_dir=str(tmp_path),
    )

    result = wp_mod.write_profile(
        name="rt_two",
        jobs=[{
            "name": "JOB_TWO",
            "type": "sql",
            "severity": "Critical",
            "section_prompt": "Check 2",
            "query": "SELECT 2 AS device, 2 AS metric_value, 'y' AS metric_name, 'ok' AS severity_hint",
        }],
        mode="append",
        profiles_dir=str(tmp_path),
    )
    assert "ERROR" not in result, result
    assert "JOB_TWO" in (tmp_path / "rt_two.md").read_text()

    merged = (tmp_path / "rt_two.md").read_text(encoding="utf-8")
    assert "JOB_ONE" in merged and "JOB_TWO" in merged
    assert merged.count("type: sql") == 2


def test_append_blocks_duplicate_name(wp_mod, tmp_path):
    wp_mod.write_profile(
        name="dup_test",
        jobs=[{"name": "DUP_NAME", "type": "sql", "severity": "Info",
               "section_prompt": "P1", "query": "SELECT 1"}],
        mode="create",
        profiles_dir=str(tmp_path),
    )
    result = wp_mod.write_profile(
        name="dup_test",
        jobs=[{"name": "DUP_NAME", "type": "sql", "severity": "Critical",
               "section_prompt": "P2", "query": "SELECT 2"}],
        mode="append",
        profiles_dir=str(tmp_path),
    )
    assert result.startswith("ERROR")
    assert "DUP_NAME" in result


def test_append_rejects_sql_without_query(wp_mod, tmp_path):
    wp_mod.write_profile(
        name="branch_test",
        jobs=[{"name": "BASE", "type": "sql", "severity": "Info",
               "section_prompt": "base", "query": "SELECT 1"}],
        mode="create",
        profiles_dir=str(tmp_path),
    )
    result = wp_mod.write_profile(
        name="branch_test",
        jobs=[{"name": "NO_QUERY", "type": "sql", "severity": "Critical",
               "section_prompt": "oops"}],  # query missing
        mode="append",
        profiles_dir=str(tmp_path),
    )
    assert result.startswith("ERROR")
    assert "query" in result.lower() or "sql" in result.lower()


# ─────────────────────────────────────────────────────────────────────
# 4. read_profile surfaces full body + frontmatter flags (via platform)
# ─────────────────────────────────────────────────────────────────────


def test_read_profile_returns_full_body_and_flags(tmp_path):
    """load_profile(action='read') must return the full body text and
    persist_findings_to_db / max_findings_per_job flags."""
    from olav.core.auditor.profile_read import read_profile

    p = tmp_path / "with_body.md"
    body = "## Narrative\n\nDetailed explanation. " * 20
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
