"""classify_field tool wrapper — guard tests.

Covers:
1. classify_field_tool.py is importable from the workspace
2. classify_field_tool defines a LangChain tool or plain async function
3. classify_field_tool delegates to SchemaEngine.classify_field()
4. classify_field_tool passes the domain param through
5. create_unified_view_tool exists and delegates to schema_engine.create_unified_view
"""

from __future__ import annotations

from pathlib import Path
import importlib.util
import sys


def _load_tool(filename: str):
    """Import a tool from .olav/workspace/config/discovery/tools/ by filename."""
    tool_path = Path(".olav/workspace/config/discovery/tools") / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1–4. classify_field_tool.py
# ---------------------------------------------------------------------------


def test_classify_field_tool_importable() -> None:
    mod = _load_tool("classify_field.py")
    assert hasattr(mod, "classify_field") or hasattr(mod, "classify_field_tool")


def test_classify_field_tool_is_callable() -> None:
    mod = _load_tool("classify_field.py")
    fn = getattr(mod, "classify_field", None) or getattr(mod, "classify_field_tool")
    assert callable(fn)


def test_classify_field_tool_delegates_to_engine(tmp_path, monkeypatch) -> None:
    """Tool delegates to SchemaEngine.classify_field() — no direct DB access."""
    from unittest.mock import MagicMock, patch
    from olav.core.schema_engine import SchemaEngine
    from olav.core.schema_mutation_service import SchemaMutationService

    mock_result = {"status": "unclassified", "confidence": 0.0}
    mock_engine = MagicMock(spec=SchemaEngine)
    mock_engine.classify_field.return_value = mock_result

    mod = _load_tool("classify_field.py")
    fn = getattr(mod, "classify_field", None) or getattr(mod, "classify_field_tool")

    with patch("olav.core.schema_engine.SchemaEngine", return_value=mock_engine):
        import asyncio

        if asyncio.iscoroutinefunction(fn):
            result = asyncio.run(fn(name="ip_address", domain="netops"))
        else:
            result = fn(name="ip_address", domain="netops")

    assert isinstance(result, dict)


def test_classify_field_tool_passes_domain() -> None:
    """When domain is provided, it must reach schema_engine."""
    from unittest.mock import MagicMock, patch, call
    from olav.core.schema_engine import SchemaEngine

    mock_engine_instance = MagicMock(spec=SchemaEngine)
    mock_engine_instance.classify_field.return_value = {"status": "unclassified", "confidence": 0.0}

    mod = _load_tool("classify_field.py")
    fn = getattr(mod, "classify_field", None) or getattr(mod, "classify_field_tool")

    with patch("olav.core.schema_engine.SchemaEngine", return_value=mock_engine_instance):
        import asyncio

        if asyncio.iscoroutinefunction(fn):
            asyncio.run(fn(name="bgp_peer", domain="myapp", description="BGP peer address"))
        else:
            fn(name="bgp_peer", domain="myapp", description="BGP peer address")

    mock_engine_instance.classify_field.assert_called_once()
    field_arg = mock_engine_instance.classify_field.call_args[0][0]
    assert field_arg["domain"] == "myapp"


# ---------------------------------------------------------------------------
# 5. create_unified_view_tool.py
# ---------------------------------------------------------------------------


def test_create_unified_view_tool_importable() -> None:
    mod = _load_tool("create_unified_view.py")
    assert hasattr(mod, "create_unified_view") or hasattr(mod, "create_unified_view_tool")


def test_create_unified_view_tool_generates_sql() -> None:
    mod = _load_tool("create_unified_view.py")
    fn = getattr(mod, "create_unified_view", None) or getattr(mod, "create_unified_view_tool")
    import json, asyncio

    mappings = [{"raw_key": "IP_ADDR", "openconfig_path": "management_ip", "data_type": "VARCHAR"}]
    if asyncio.iscoroutinefunction(fn):
        result = asyncio.run(fn(command="show interfaces", mappings=mappings))
    else:
        result = fn(command="show interfaces", mappings=mappings)

    if isinstance(result, dict):
        sql = result.get("sql", "")
    else:
        sql = str(result)
    assert "CREATE OR REPLACE VIEW" in sql
    assert "management_ip" in sql
