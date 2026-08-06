"""Guides are memory shipped in wheels — the repo boundary applies to them too.

CLAUDE.md forbids olav core carrying network-domain or enterprise semantics, and
allows only ``olav-netops -> olav``. Until 2026-08-05 nothing checked that for
guide content, and the audit found breaches in both directions: nine
network-domain guides inside the platform wheel, five platform-declared guides
shipped by the extension, and agent names (``ops``, ``sim``) that match no real
workspace at all (dev_docs/117).

That last one only became load-bearing when ``agent:`` started governing recall
scope: a guide naming a non-existent agent is invisible to every agent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PLATFORM = _ROOT / "src" / "olav" / "data" / "workspace"
_NETOPS = _ROOT / "olav-netops" / "src" / "olav_netops" / "data" / "skillpack" / ".olav" / "workspace"

# Platform agents are the top-level workspace dirs the wheel ships.
_PLATFORM_AGENTS = {"core", "admin", "audit", "devops", "services"}
# netops sub-agents own guides too; scope is matched against these names.
_NETOPS_AGENTS = {
    "netops", "analyzer", "collector", "importer", "learner",
    "reporter", "simulator", "topology",
}
_VALID_AGENTS = _PLATFORM_AGENTS | _NETOPS_AGENTS

# Tool-usage guides opt into cross-agent recall; nothing else may.
_GLOBAL_ALLOWED = {
    "format_and_export_calling_convention",
    "sql_export_cite_the_full_csv",
    "schema_introspection_via_describe_table",
    "write_class_tool_call_directive",
    "viz_drawio_xml_rules",
    "diagram_format_choice_and_minimal_examples",
    # Routes syslog questions to the search_logs TOOL rather than execute_sql.
    # Subject looks network-ish; function is tool routing, and both core and
    # audit/explorer hold the tool.
    "syslog_search_during_troubleshooting",
}

# Empty, and meant to stay that way. It held six network-type playbooks that
# shipped under the platform's audit/explorer; on 2026-08-06 they moved to
# olav-presales together with the explorer agent itself, which is an open-ended
# assessment persona rather than platform runtime. Recording them here rather
# than tolerating them silently is what made the debt visible enough to settle.
# Shrink this set; never grow it.
_KNOWN_PLATFORM_NETWORK_GUIDES: set[str] = set()


def _field(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(\S+)", text, re.M)
    return m.group(1) if m else ""


def _guides(root: Path) -> list[tuple[Path, str, str, str]]:
    out = []
    if not root.exists():
        return out
    for f in sorted(root.rglob("*.guide.yaml")):
        t = f.read_text(encoding="utf-8")
        out.append((f, _field(t, "intent"), _field(t, "agent"), _field(t, "scope")))
    return out


class TestAgentNamesAreReal:
    """An agent name that matches no workspace makes the guide unrecallable."""

    @pytest.mark.parametrize("root", [_PLATFORM, _NETOPS], ids=["olav", "olav-netops"])
    def test_every_agent_exists(self, root):
        bad = [
            (f.name, agent)
            for f, _, agent, _ in _guides(root)
            if agent and agent not in _VALID_AGENTS
        ]
        assert not bad, (
            f"guides naming an agent that does not exist: {bad}. "
            f"Valid: {sorted(_VALID_AGENTS)}"
        )


class TestScopeOptIn:
    @pytest.mark.parametrize("root", [_PLATFORM, _NETOPS], ids=["olav", "olav-netops"])
    def test_only_tool_usage_declares_global(self, root):
        bad = [
            intent for _, intent, _, scope in _guides(root)
            if scope == "global" and intent not in _GLOBAL_ALLOWED
        ]
        assert not bad, (
            f"these declare scope: global without being platform tool usage: {bad}. "
            "Domain knowledge going global is what ate the top-k slots."
        )

    @pytest.mark.parametrize("root", [_PLATFORM, _NETOPS], ids=["olav", "olav-netops"])
    def test_no_scope_other_than_global_or_a_real_agent(self, root):
        bad = [
            (intent, scope) for _, intent, _, scope in _guides(root)
            if scope and scope != "global" and scope not in _VALID_AGENTS
        ]
        assert not bad, f"unknown scope values: {bad}"


class TestRepoBoundary:
    def test_platform_wheel_ships_no_new_network_domain_guides(self):
        """olav core must not carry network-domain semantics (CLAUDE.md)."""
        offenders = {
            intent for _, intent, agent, _ in _guides(_PLATFORM)
            if agent in (_NETOPS_AGENTS - {"netops"}) or agent == "netops"
        }
        new = offenders - _KNOWN_PLATFORM_NETWORK_GUIDES
        assert not new, (
            f"new network-domain guides in the platform wheel: {sorted(new)}. "
            "They belong in olav-netops."
        )

    def test_the_known_exception_list_is_not_stale(self):
        """If a listed guide has been moved out, drop it from the list."""
        present = {intent for _, intent, _, _ in _guides(_PLATFORM)}
        stale = _KNOWN_PLATFORM_NETWORK_GUIDES - present
        assert not stale, (
            f"these have been moved out — remove them from "
            f"_KNOWN_PLATFORM_NETWORK_GUIDES: {sorted(stale)}"
        )

    def test_extension_does_not_ship_platform_declared_guides(self):
        """olav-netops -> olav is the only allowed direction (ADR-0002): an
        extension shipping `agent: core` guides inverts it."""
        bad = [
            intent for _, intent, agent, _ in _guides(_NETOPS)
            if agent in _PLATFORM_AGENTS
        ]
        assert not bad, (
            f"olav-netops ships guides declared for a platform agent: {bad}. "
            "Platform knowledge belongs in the platform wheel."
        )
