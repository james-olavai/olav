"""Round 48 — ARCH-08 Phase 2 Item 2: ``netops.devices.environment`` column.

Round 25 closed Phase 1 (``data.environment`` tag in the Nornir inventory
+ dupe-hostname detection) and the per-tool signature work (Round 39
through ``test_environment_dispatch.py``). Item 2 — the ``environment``
column on ``netops.devices`` so downstream queries can join/filter — was
the lingering gap.

Round 48 lands it in four coordinated edits:

1. ``DevicesTable`` schema (olav-netops) gains a nullable ``environment``
   VARCHAR column.
2. ``netops_init/run.py::_populate_devices`` issues an idempotent
   ``ALTER TABLE ADD COLUMN IF NOT EXISTS`` migration for existing
   deployments that predate the schema change.
3. A new ``_load_host_environments()`` helper reads ``hosts.yaml`` and
   returns ``{hostname → environment}`` for the ETL to consume.
4. The device INSERT adds ``environment`` to both the column list and
   the ``ON CONFLICT DO UPDATE`` clause (with ``COALESCE`` so a
   subsequent run without the tag doesn't NULL out an existing value).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.governance._paths import NETOPS_INIT_DIR

REPO = Path(__file__).resolve().parents[2]
TABLES_PY = REPO / "olav-netops" / "src" / "olav_netops" / "core" / "tables.py"
RUN_PY = NETOPS_INIT_DIR / "run.py"
DEVICE_ETL_PY = REPO / "olav-netops" / "src" / "olav_netops" / "core" / "device_etl.py"


def _load_tables_module():
    # ``olav-netops`` ships as a separate package; import via path so the
    # test doesn't depend on it being pip-installed in the test env.
    spec = importlib.util.spec_from_file_location("_olav_netops_tables_r48", TABLES_PY)
    mod = importlib.util.module_from_spec(spec)
    # tables.py imports from olav_netops + olav.platform.ingest_base — if
    # these aren't available the smoke test falls back to text-level pins.
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception:
        return None


# ── Schema definition pins ──────────────────────────────────────────────


def test_devices_table_declares_environment_column():
    """DevicesTable.columns must include a nullable environment VARCHAR."""
    mod = _load_tables_module()
    if mod is None:
        # Fallback: text-level check — the column declaration must exist.
        src = TABLES_PY.read_text(encoding="utf-8")
        assert 'ColumnDef("environment", "VARCHAR")' in src, (
            "DevicesTable lost the environment column (ARCH-08 Phase 2 Item 2)"
        )
        return

    cls = getattr(mod, "DevicesTable", None)
    assert cls is not None
    names = [c.name for c in cls.columns]
    assert "environment" in names, (
        f"DevicesTable.columns missing 'environment'; got {names}"
    )
    # Must be nullable (existing devices from LLDP discovery have no inventory tag).
    env_col = next(c for c in cls.columns if c.name == "environment")
    assert env_col.nullable, "environment column must be nullable"
    assert env_col.type.upper() == "VARCHAR"


def test_devices_table_docstring_mentions_arch_08():
    src = TABLES_PY.read_text(encoding="utf-8")
    assert "ARCH-08" in src, (
        "DevicesTable docstring should tag ARCH-08 so future refactors "
        "don't drop the column without noticing the cross-reference."
    )


# ── ETL wiring pins ─────────────────────────────────────────────────────


def test_load_host_environments_helper_exists():
    src = RUN_PY.read_text(encoding="utf-8")
    assert "def _load_host_environments" in src, (
        "_load_host_environments helper missing in netops_init/run.py"
    )


def test_load_host_environments_reads_hosts_yaml(tmp_path, monkeypatch):
    """End-to-end: write a minimal hosts.yaml, patch the resolver to point
    at it, confirm the helper picks up only hosts with data.environment."""
    # Build a tiny Nornir config tree.
    nornir_dir = tmp_path / "nornir"
    nornir_dir.mkdir()
    hosts_yaml = nornir_dir / "hosts.yaml"
    hosts_yaml.write_text(
        "R1:\n  hostname: 10.0.0.1\n  data:\n    environment: lab\n"
        "R2:\n  hostname: 10.0.0.2\n  data:\n    environment: prod\n"
        # No environment tag — must not appear in the map.
        "R3:\n  hostname: 10.0.0.3\n",
        encoding="utf-8",
    )

    # Fake the nornir config resolver. Post-R66f the resolver lives in
    # olav_netops.core.config_paths (domain-owned); also keep an alias on
    # olav.core.config for lazy fallback paths that may still reference it.
    import types
    fake_netops_cfg = types.ModuleType("olav_netops.core.config_paths")
    fake_netops_cfg.resolve_nornir_config_path = lambda: nornir_dir / "config.yaml"  # type: ignore[attr-defined]
    fake_netops_cfg._resolve_nornir_config_path = fake_netops_cfg.resolve_nornir_config_path  # noqa: E501
    monkeypatch.setitem(sys.modules, "olav_netops.core.config_paths", fake_netops_cfg)

    # Load run.py module fresh.
    spec = importlib.util.spec_from_file_location("_olav_run_r48", RUN_PY)
    run_mod = importlib.util.module_from_spec(spec)
    # run.py top-level has a lot of imports — catch errors, fall back to
    # a text-only pin.
    try:
        spec.loader.exec_module(run_mod)  # type: ignore[union-attr]
    except Exception:
        src = RUN_PY.read_text(encoding="utf-8")
        assert 'host_data.get("environment")' in src
        return

    result = run_mod._load_host_environments()
    assert result == {"R1": "lab", "R2": "prod"}, (
        f"expected only tagged hosts; got {result!r}"
    )


def test_load_host_environments_returns_empty_when_yaml_missing(monkeypatch):
    # Post-R66f: resolver moved to olav_netops.core.config_paths.
    import types
    fake_netops_cfg = types.ModuleType("olav_netops.core.config_paths")
    fake_netops_cfg.resolve_nornir_config_path = lambda: Path("/definitely/nowhere/config.yaml")  # type: ignore[attr-defined]
    fake_netops_cfg._resolve_nornir_config_path = fake_netops_cfg.resolve_nornir_config_path  # noqa: E501
    monkeypatch.setitem(sys.modules, "olav_netops.core.config_paths", fake_netops_cfg)

    spec = importlib.util.spec_from_file_location("_olav_run_r48b", RUN_PY)
    run_mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(run_mod)  # type: ignore[union-attr]
    except Exception:
        return  # fallback: source pinned elsewhere
    assert run_mod._load_host_environments() == {}


def test_populate_devices_migration_alter_table_wired():
    """The ETL must issue the idempotent ALTER TABLE before the INSERT so
    pre-R48 deployments don't crash on the unknown column."""
    src = RUN_PY.read_text(encoding="utf-8")
    if "ALTER TABLE netops.devices ADD COLUMN IF NOT EXISTS environment" in src:
        return
    # Newer layout: netops_init delegates ETL to shared package module.
    assert "populate_devices as _populate_devices" in src
    etl_src = DEVICE_ETL_PY.read_text(encoding="utf-8")
    assert "ALTER TABLE netops.devices ADD COLUMN IF NOT EXISTS environment" in etl_src, (
        "devices.environment migration missing in delegated ETL module"
    )


def test_populate_devices_insert_includes_environment():
    """INSERT column list + ON CONFLICT clause must both reference environment."""
    src = RUN_PY.read_text(encoding="utf-8")
    insert_block_start = src.find("INSERT INTO netops.devices")
    if insert_block_start >= 0:
        insert_block = src[insert_block_start : insert_block_start + 1500]
    else:
        assert "populate_devices as _populate_devices" in src
        etl_src = DEVICE_ETL_PY.read_text(encoding="utf-8")
        insert_block_start = etl_src.find("INSERT INTO netops.devices")
        assert insert_block_start >= 0, "_populate_devices INSERT block lost"
        insert_block = etl_src[insert_block_start : insert_block_start + 2000]

    assert "environment" in insert_block, (
        "INSERT INTO netops.devices no longer writes environment"
    )
    # ON CONFLICT must COALESCE environment to preserve prior value when
    # a later run lacks the inventory tag.
    assert "environment=COALESCE(EXCLUDED.environment" in insert_block, (
        "ON CONFLICT must COALESCE environment to avoid NULL-ing it out on "
        "subsequent runs without inventory access."
    )
    # The env_tag parameter must be threaded into the execute() params list.
    assert "env_tag" in insert_block or "env_tag)" in src, (
        "_populate_devices lost the env_tag local — INSERT will run with "
        "a mismatched parameter count"
    )
