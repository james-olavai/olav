"""A guide's ``agent:`` must govern who can recall it.

Every guide used to be primed with ``scope="global"``, so ``agent:`` only shaped
the memory ID and never reached the retrieval filter — the middleware's
``(scope = 'global' OR scope = '<agent>')`` predicate matched everything. All 43
guides therefore competed for every agent's top-k, and measurement on the demo
host showed two of them winning 7 of 7 and 6 of 7 unrelated probes (including
"hello" and "what is the weather"), taking two of the three medium-tier slots
(dev_docs/117).

Scope now defaults to the owning agent. Cross-agent visibility is an explicit
opt-in reserved for platform *tool* usage — argument shape, calling convention,
output format — never for domain knowledge or workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from olav.core.memory.guide_kb import UsageGuide, discover_guides

_PLATFORM_ROOT = Path(__file__).resolve().parents[2] / "src" / "olav" / "data" / "workspace"


def _write(tmp_path: Path, **fields) -> Path:
    doc = {
        "schema_version": 1,
        "intent": "t",
        "agent": "netops",
        "keywords": ["k"],
        "body": "b",
    }
    doc.update(fields)
    p = tmp_path / f"{doc['intent']}.guide.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


class TestEffectiveScope:
    def test_defaults_to_the_owning_agent(self, tmp_path):
        g = UsageGuide.from_yaml(_write(tmp_path, agent="netops"))
        assert g.effective_scope == "netops", (
            "without an explicit scope a guide belongs to its agent — the old "
            "hardcoded global is what let domain guides leak everywhere"
        )

    def test_explicit_global_is_honoured(self, tmp_path):
        g = UsageGuide.from_yaml(_write(tmp_path, agent="core", scope="global"))
        assert g.effective_scope == "global"

    def test_explicit_scope_can_differ_from_agent(self, tmp_path):
        g = UsageGuide.from_yaml(_write(tmp_path, agent="core", scope="audit"))
        assert g.effective_scope == "audit"

    def test_blank_scope_falls_back_to_agent(self, tmp_path):
        g = UsageGuide.from_yaml(_write(tmp_path, agent="audit", scope="   "))
        assert g.effective_scope == "audit"

    def test_scope_is_optional_so_existing_guides_still_load(self, tmp_path):
        g = UsageGuide.from_yaml(_write(tmp_path))
        assert g.scope is None and g.effective_scope == "netops"


class TestPrimingUsesTheEffectiveScope:
    def test_add_memory_receives_effective_scope_not_a_literal(self):
        """Judged on the AST, not on a substring — the comment above the fix
        quotes the old `scope="global"` to explain it, and a text search flags
        the prose describing the very bug being fixed. Third time today.
        """
        import ast

        src = (
            Path(__file__).resolve().parents[2]
            / "src" / "olav" / "core" / "memory" / "guide_kb.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(src)

        scope_args = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fname != "add_memory":
                continue
            for kw in node.keywords:
                if kw.arg == "scope":
                    scope_args.append(ast.unparse(kw.value))

        assert scope_args, "no add_memory(scope=...) call found"
        for expr in scope_args:
            assert expr != "'global'" and expr != '"global"', (
                f"add_memory still hardcodes the scope: {expr}"
            )
            assert "effective_scope" in expr, (
                f"scope must come from the guide, got {expr}"
            )


class TestShippedPlatformGuides:
    """Guards on what the platform wheel actually ships."""

    @staticmethod
    def _guides():
        return discover_guides(_PLATFORM_ROOT)

    def test_only_tool_usage_guides_are_global(self):
        """Domain knowledge going global is how the top-k slots got eaten."""
        allowed = {
            "format_and_export_calling_convention",
            "sql_export_cite_the_full_csv",
            "schema_introspection_via_describe_table",
            "write_class_tool_call_directive",
            "viz_drawio_xml_rules",
            "diagram_format_choice_and_minimal_examples",
            # Tool routing despite a network-sounding subject: it sends syslog
            # questions to the search_logs tool instead of execute_sql.
            "syslog_search_during_troubleshooting",
        }
        offenders = sorted(
            g.intent for g in self._guides()
            if g.effective_scope == "global" and g.intent not in allowed
        )
        assert not offenders, (
            f"these declare scope: global but are not platform tool usage: {offenders}. "
            "Tool usage means argument shape / calling convention / output format."
        )

    def test_every_guide_resolves_to_a_scope(self):
        assert all(g.effective_scope for g in self._guides())
