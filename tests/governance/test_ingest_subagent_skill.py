"""Governance — ``netops/ingest`` sub-agent contract pins.

What this protects against:
  * SKILL.md silently desyncing from the design (tool whitelist, agent_type,
    thinking_mode)
  * netops SKILL.md dropping the sibling-of-collect wire-up
  * Tool wrapper imports drifting and producing un-runnable @tool objects

Tests are read-only: parse YAML front-matter, inspect tool decorators.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


_INGEST_DIR = (
    Path(__file__).parent.parent.parent
    / "olav-netops" / ".olav" / "workspace" / "netops" / "importer"
)
_NETOPS_AGENT_MD = (
    Path(__file__).parent.parent.parent
    / "olav-netops" / ".olav" / "workspace" / "netops" / "SKILL.md"
)


def _parse_front_matter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"missing YAML front-matter in {md_path}"
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm) or {}


# ── SKILL.md ──────────────────────────────────────────────────────────


class TestIngestSkillFrontMatter:
    def test_skill_md_exists(self):
        assert (_INGEST_DIR / "SKILL.md").is_file()

    def test_name_is_ingest(self):
        fm = _parse_front_matter(_INGEST_DIR / "SKILL.md")
        assert fm["name"] == "importer"

    def test_agent_type_api(self):
        fm = _parse_front_matter(_INGEST_DIR / "SKILL.md")
        # Matches the rest of the netops sub-agents (collect, analyze, sim …):
        # the orchestrator handles planning, sub-agents just execute tools.
        assert fm["agent_type"] == "api"

    def test_thinking_mode_enabled(self):
        """Format classification (rancid vs canonical bundle vs loose dump)
        is fuzzy work; nothink mis-routes in repeated trials per dev_docs/80."""
        fm = _parse_front_matter(_INGEST_DIR / "SKILL.md")
        assert fm["thinking_mode"] == "enabled"

    def test_tool_whitelist_pins(self):
        fm = _parse_front_matter(_INGEST_DIR / "SKILL.md")
        tools = set(fm.get("tools", []))
        script_names = {s["name"] for s in fm.get("scripts", [])}
        # execute_skill_script is the sole @tool — all others are scripts.
        assert "execute_skill_script" in tools, f"missing execute_skill_script in tools: {tools}"
        # survey_bundle replaced ls/read_file/glob/grep (rev ~302 tool-bloat refactor).
        assert "survey_bundle" in script_names, f"missing survey_bundle in scripts: {script_names}"
        assert "ingest_snapshot" in script_names, f"missing ingest_snapshot in scripts: {script_names}"
        assert "validate_bundle" in script_names, f"missing validate_bundle in scripts: {script_names}"
        assert "discover_platform_for_host" in script_names, (
            f"missing discover_platform_for_host in scripts: {script_names}"
        )
        # Native deepagents tools removed: format discovery is now handled by
        # survey_bundle script; platform_sample_lines replaces read_file Tier 3 path.
        for removed in ("ls", "read_file", "glob", "grep"):
            assert removed not in tools, (
                f"{removed} should not be in tools after survey_bundle migration"
            )

    def test_no_nested_subagents(self):
        """Ingest is a leaf — never delegates further."""
        fm = _parse_front_matter(_INGEST_DIR / "SKILL.md")
        assert not fm.get("subagents"), "ingest must not declare nested subagents"

    def test_reference_guides_declared(self):
        fm = _parse_front_matter(_INGEST_DIR / "SKILL.md")
        guides = {g["path"] for g in fm.get("dynamic_context", [])}
        assert "./references/bundle_schema.guide.yaml" in guides
        assert "./references/vendor_dump_heuristics.guide.yaml" in guides
        assert "./references/rancid_format.guide.yaml" in guides
        # Tier 3 LLM signature table for platform discovery.
        assert "./references/platform_signatures.guide.yaml" in guides


# ── netops SKILL.md wire-up ───────────────────────────────────────────


class TestNetopsAgentMdWiring:
    def test_ingest_path_listed_in_subagents(self):
        fm = _parse_front_matter(_NETOPS_AGENT_MD)
        sub_paths = {s["path"] for s in fm.get("subagents", [])}
        assert "./importer/SKILL.md" in sub_paths, (
            f"./importer/SKILL.md missing from netops SKILL.md subagents: {sub_paths}"
        )

    def test_collect_still_listed(self):
        """Sanity — adding importer must not displace collector (we want both)."""
        fm = _parse_front_matter(_NETOPS_AGENT_MD)
        sub_paths = {s["path"] for s in fm.get("subagents", [])}
        assert "./collector/SKILL.md" in sub_paths

    def test_route_keywords_mention_ingest(self):
        fm = _parse_front_matter(_NETOPS_AGENT_MD)
        joined = " ".join(fm.get("route_keywords", []))
        # Pin both English + Chinese routing tokens — the orchestrator's
        # keyword route is fragile if either drops out.
        assert "ingest" in joined.lower()
        assert "bundle" in joined.lower()
        assert "导入" in joined  # Chinese: import


# ── Tool wrapper modules are importable ───────────────────────────────


class TestToolWrappersLoad:
    def test_ingest_snapshot_tool_loads(self):
        import importlib.util
        path = _INGEST_DIR / "scripts" / "ingest_snapshot.py"
        spec = importlib.util.spec_from_file_location("ingest_snapshot_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "ingest_snapshot"), "@tool fn missing"

    def test_validate_bundle_tool_loads(self):
        import importlib.util
        path = _INGEST_DIR / "scripts" / "validate_bundle.py"
        spec = importlib.util.spec_from_file_location("validate_bundle_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "validate_bundle"), "@tool fn missing"

    def test_discover_platform_tool_loads(self):
        import importlib.util
        path = _INGEST_DIR / "scripts" / "discover_platform.py"
        spec = importlib.util.spec_from_file_location("discover_platform_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "discover_platform_for_host"), "@tool fn missing"

    def test_survey_bundle_script_loads(self):
        import importlib.util
        path = _INGEST_DIR / "scripts" / "survey_bundle.py"
        spec = importlib.util.spec_from_file_location("survey_bundle_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "survey_bundle"), "survey_bundle fn missing"

    def test_survey_bundle_unknown_path(self):
        """survey_bundle should return an error dict, not raise."""
        import importlib.util
        path = _INGEST_DIR / "scripts" / "survey_bundle.py"
        spec = importlib.util.spec_from_file_location("survey_bundle_test2", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.survey_bundle("/nonexistent/path/xyz")
        assert "error" in result

    def test_survey_bundle_canonical_detection(self, tmp_path):
        """survey_bundle detects canonical bundle format via manifest.yaml."""
        import importlib.util
        # Create a minimal canonical bundle
        (tmp_path / "manifest.yaml").write_text("schema_version: '1.0'\nhosts: {}\n")
        path = _INGEST_DIR / "scripts" / "survey_bundle.py"
        spec = importlib.util.spec_from_file_location("survey_bundle_test3", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.survey_bundle(str(tmp_path))
        assert result["format"] == "canonical"
        assert result["ingest_supported"] is True
        assert "notes" in result

    def test_survey_bundle_unsupported_format_returns_ingest_supported_false(self, tmp_path):
        """Non-canonical bundles set ingest_supported=False."""
        import importlib.util
        # Simulate vendor dump: loose .txt files, no manifest
        (tmp_path / "R1.txt").write_text("R1#\nshow version\n")
        path = _INGEST_DIR / "scripts" / "survey_bundle.py"
        spec = importlib.util.spec_from_file_location("survey_bundle_test4", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.survey_bundle(str(tmp_path))
        assert result["format"] == "vendor_dump"
        assert result["ingest_supported"] is False
        assert "R1" in result["hosts"]
