from __future__ import annotations

import importlib

mod = importlib.import_module("olav.core.curator.fuzzy_map_schema")


def _invoke(**kwargs) -> dict:
    if hasattr(mod.fuzzy_map_schema, "invoke"):
        return mod.fuzzy_map_schema.invoke(kwargs)
    return mod.fuzzy_map_schema(**kwargs)


def test_fuzzy_map_schema_success_path(monkeypatch):
    monkeypatch.setattr(mod, "_load_baselines", lambda: {})
    monkeypatch.setattr(
        mod,
        "_get_db_schema",
        lambda _table: {"description": "interfaces", "fields": {"ifname": "VARCHAR", "admin_state": "VARCHAR"}},
    )
    monkeypatch.setattr(mod, "_get_standard_command", lambda command, _platform: command)
    monkeypatch.setattr(mod, "_get_standard_sample", lambda _platform, _command: None)
    monkeypatch.setattr(mod, "_check_cache", lambda _vendor, _command: None)
    monkeypatch.setattr(
        mod,
        "_call_llm_for_mapping",
        lambda *_args, **_kwargs: [
            {"raw_key": "name", "cisco_key": "ifname"},
            {"raw_key": "state", "cisco_key": "admin_state"},
        ],
    )
    monkeypatch.setattr(mod, "_save_mappings", lambda *_args, **_kwargs: None)

    out = _invoke(
        vendor="huawei",
        platform="huawei_vrp",
        command="display interface brief",
        raw_data=[{"name": "GE0/0/1", "state": "up", "mtu": 1500}],
        table_name="interfaces",
    )

    assert out["status"] == "success"
    assert out["mappings"] == [
        {"raw_key": "name", "cisco_key": "ifname"},
        {"raw_key": "state", "cisco_key": "admin_state"},
    ]
    assert out["normalized_data"] == [{"ifname": "GE0/0/1", "admin_state": "up", "mtu": 1500}]


def test_fuzzy_map_schema_errors_when_raw_data_empty(monkeypatch):
    monkeypatch.setattr(mod, "_load_baselines", lambda: {})
    monkeypatch.setattr(
        mod,
        "_get_db_schema",
        lambda _table: {"description": "interfaces", "fields": {"ifname": "VARCHAR"}},
    )
    monkeypatch.setattr(mod, "_get_standard_command", lambda command, _platform: command)
    monkeypatch.setattr(mod, "_get_standard_sample", lambda _platform, _command: None)
    monkeypatch.setattr(mod, "_check_cache", lambda _vendor, _command: None)

    out = _invoke(
        vendor="huawei",
        command="display interface brief",
        raw_data=[],
        table_name="interfaces",
    )

    assert out["status"] == "error"
    assert out["error"] == "No raw data provided"
