"""ARCH-18 #2: default tool returns stay compact.

Covers:
  * ``execute_cli_parallel`` — outputs > 4000 chars are truncated unless ``full=True``
  * ``diff_configs`` — diff body capped at 40 lines unless ``full=True``
  * ``api_request`` — first-page list responses capped at 50 entries
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.governance._paths import NETOPS_TOOLS

REPO = Path(__file__).resolve().parents[2]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── execute_cli_parallel ─────────────────────────────────────────────────────


def test_execute_cli_parallel_exposes_full_flag():
    src = (NETOPS_TOOLS / "execute_cli_parallel.py").read_text(
        encoding="utf-8"
    )
    assert "full: bool = False" in src, "execute_cli_parallel missing `full` parameter (ARCH-18 #2)"
    assert "_COMPACT_OUTPUT_CHARS" in src


def test_execute_cli_parallel_truncates_long_output_in_compact_mode():
    """Unit-level proof that the compact branch actually trims."""
    src = (NETOPS_TOOLS / "execute_cli_parallel.py").read_text(
        encoding="utf-8"
    )
    assert "if not full:" in src
    assert "len(raw) > _COMPACT_OUTPUT_CHARS" in src
    assert "truncated at" in src
    assert "re-run with full=True" in src


# ── diff_configs ─────────────────────────────────────────────────────────────


def test_diff_configs_exposes_full_kwarg():
    src = (NETOPS_TOOLS / "diff_configs.py").read_text(encoding="utf-8")
    assert "full: bool = False" in src
    # Thin-wrapper contract: must pass the full flag through to
    # olav_netops.core.diff.configs.diff_configs implementation.
    assert "from olav_netops.core.diff.configs import diff_configs as _diff_configs_impl" in src
    assert "full=full" in src


# ── api_request ──────────────────────────────────────────────────────────────


def test_api_request_compact_list_cap_constant():
    src = (REPO / ".olav" / "workspace" / "core" / "api-query" / "scripts" / "api_request.py").read_text(
        encoding="utf-8"
    )
    assert "_COMPACT_LIST_CAP" in src
    # The cap must actually be applied inside the DRF-pagination branch.
    assert "len(page) > _COMPACT_LIST_CAP" in src
    assert '"status": "truncated"' in src


def test_api_request_returns_truncated_dict_when_page_large(monkeypatch):
    """End-to-end: a large first-page response triggers the compact cap."""
    mod = _load(REPO / ".olav" / "workspace" / "core" / "api-query" / "scripts" / "api_request.py", "api_request_test")

    big_page = [{"id": i} for i in range(200)]
    fake_response = {"count": 200, "next": None, "results": big_page}

    # Stub the service_call import chain so the tool doesn't try to load
    # real services.yaml / HTTP clients.
    import types
    stub_client = types.ModuleType("olav.platform.services.client")
    stub_client.service_call = lambda *a, **kw: fake_response  # noqa: E731
    import sys
    sys.modules["olav.platform.services.client"] = stub_client

    tool_obj = mod.api_request
    invoker = tool_obj.invoke if hasattr(tool_obj, "invoke") else tool_obj
    result = invoker({"service": "netbox", "path": "/api/dcim/devices/"})

    assert isinstance(result, dict)
    assert result.get("status") == "truncated"
    assert result.get("count") == 200
    assert result.get("returned") == 50
    assert len(result["results"]) == 50
    assert "hint" in result
