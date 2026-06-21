"""Guards the dev_docs/97 fix for the db-query / api-query "guess the skill_name" bug.

Sub-agents get no SkillsMiddleware section; their only handle to a ``scripts:``
entry is the generic ``execute_skill_script`` tool, whose docstring example
(``skill_name="lab"``) small models copied verbatim — so api-query made 0/8 and
db-query 0/76 calls with the correct ``skill_name``. The fix injects the exact
call shape (with the agent's OWN skill_name) into every script-bearing
sub-agent's prompt. These tests pin that injection + the db-query removal.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter

from olav.agents.agent import _inject_script_recipe

_CORE = Path("src/olav/data/workspace/core")


def test_recipe_injects_own_skill_name_and_scripts():
    meta = {
        "tools": ["execute_skill_script", "execute_sql"],
        "scripts": [
            {"name": "api_request", "description": "HTTP to a service", "file": "api_request.py"},
            {"name": "service_health", "description": "Health check", "file": "service_health.py"},
        ],
    }
    out = _inject_script_recipe("BODY", "api-query", meta)
    # the exact call shape with the agent's OWN skill_name must be present
    assert 'execute_skill_script(skill_name="api-query", script_name="api_request.py"' in out
    assert 'execute_skill_script(skill_name="api-query", script_name="service_health.py"' in out
    assert "BODY" in out  # original prompt preserved


def test_recipe_skipped_without_execute_skill_script_tool():
    # An agent whose scripts are pipeline-invoked (no execute_skill_script in
    # tools) must NOT get the recipe — scripts are documentation-only there.
    meta = {"tools": ["execute_sql"], "scripts": [{"name": "x", "file": "x.py"}]}
    assert _inject_script_recipe("BODY", "foo", meta) == "BODY"


def test_recipe_skipped_without_scripts():
    meta = {"tools": ["execute_skill_script"], "scripts": []}
    assert _inject_script_recipe("BODY", "foo", meta) == "BODY"


def test_api_query_is_eligible_for_recipe():
    """api-query declares scripts + execute_skill_script, so the recipe fires."""
    fm = frontmatter.load(str(_CORE / "api-query" / "SKILL.md"))
    tools = fm.metadata.get("tools") or []
    tool_names = {t if isinstance(t, str) else t.get("name") for t in tools}
    assert "execute_skill_script" in tool_names
    assert fm.metadata.get("scripts"), "api-query must declare scripts for the recipe to apply"


def test_db_query_removed_from_core():
    """db-query subagent deleted (redundant with core's execute_sql @tool)."""
    assert not (_CORE / "db-query").exists(), "db-query dir should be deleted"
    fm = frontmatter.load(str(_CORE / "SKILL.md"))
    subs = fm.metadata.get("subagents", [])
    paths = [(s.get("path") if isinstance(s, dict) else s) for s in subs]
    assert not any("db-query" in (p or "") for p in paths), "db-query must not be a core subagent"
    # the surviving delegate subagents
    assert any("api-query" in (p or "") for p in paths)
    assert any("writer" in (p or "") for p in paths)
