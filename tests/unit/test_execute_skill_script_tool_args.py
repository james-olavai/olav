"""execute_skill_script @tool arg-shape coercion (2026-07-25 live e2e finding).

A live gemma4-31b run nested skill_name/script_name INSIDE script_args instead
of at the top level, on 6 consecutive calls — tripping the tool-loop breaker
before any subprocess ran. Pydantic-layer coercion pulls them out, per
CLAUDE.md's "fix call-construction errors at the Pydantic layer" rule.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _args():
    from olav.data.workspace.core.tools.execute_skill_script import _ExecuteSkillScriptArgs
    return _ExecuteSkillScriptArgs


def test_top_level_call_is_unaffected():
    Args = _args()
    a = Args(skill_name="presales", script_name="x.py", script_args={"foo": "bar"})
    assert a.skill_name == "presales"
    assert a.script_name == "x.py"
    assert a.script_args == {"foo": "bar"}


def test_nested_names_are_pulled_to_top_level():
    Args = _args()
    a = Args(script_args={"skill_name": "designer", "script_name": "compute_sizing.py",
                          "run_id": "run-x"})
    assert a.skill_name == "designer"
    assert a.script_name == "compute_sizing.py"
    assert a.script_args == {"run_id": "run-x"}  # names popped out, real args kept


def test_top_level_wins_when_both_present():
    Args = _args()
    a = Args(skill_name="designer", script_name="compute_sizing.py",
             script_args={"skill_name": "wrong", "script_name": "wrong.py"})
    assert a.skill_name == "designer"
    assert a.script_name == "compute_sizing.py"


def test_missing_names_entirely_still_raises():
    import pytest
    from pydantic import ValidationError
    Args = _args()
    with pytest.raises(ValidationError):
        Args(script_args={"run_id": "run-x"})


def test_tool_invoke_under_the_real_discovery_loader():
    """Regression: the module-scope tests above import this file via a normal
    `import` (registered in sys.modules), which pydantic's lazy forward-ref
    resolution relies on — and so never caught that the REAL loader,
    olav.core.tool_discovery, loads workspace tool files via
    importlib.util.spec_from_file_location WITHOUT registering them in
    sys.modules. Under that loader `_ExecuteSkillScriptArgs` (a `from __future__
    import annotations` model) raised `PydanticUserError: not fully defined` on
    the FIRST real tool call, live, in production — reproduce that exact path
    here so a future change can't silently regress it again."""
    import importlib.util

    file_path = (Path(__file__).resolve().parents[2] / "src" / "olav" / "data" /
                "workspace" / "core" / "tools" / "execute_skill_script.py")
    spec = importlib.util.spec_from_file_location("_test_olav_tool_execute_skill_script",
                                                   file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # deliberately NOT registered in sys.modules

    # Would previously raise pydantic.errors.PydanticUserError before the
    # script ever ran — the assertion here is that this call returns at all.
    result = module.execute_skill_script.invoke({
        "script_args": {"action": "status", "script_name": "project_admin.py",
                        "skill_name": "presales"},
    })
    assert result.get("status") in ("ok", "error")
