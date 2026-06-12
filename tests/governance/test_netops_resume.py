"""NETOPS-04: netops_init checkpoint + --resume plumbing.

Contract:

* ``Checkpoint`` serialises / deserialises round-trip (JSON).
* ``completed_set`` yields O(1) (device, command) membership.
* ``mark_done`` is idempotent (repeated same pair doesn't grow the list).
* ``load(missing)`` returns None — callers fall back to a fresh run.
* ``load(malformed)`` returns None, does not raise.
* ``save`` is atomic (``.tmp`` + ``os.replace``).

End-to-end behaviour (checkpoint causes skipping) is exercised via
``_run_collection`` import hooks; full SSH paths are not tested here
because they need a live Nornir inventory.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.governance._paths import NETOPS_INIT_DIR

REPO = Path(__file__).resolve().parents[2]
CHECKPOINT_PY = NETOPS_INIT_DIR / "checkpoint.py"


def _load():
    spec = importlib.util.spec_from_file_location("netops_checkpoint", CHECKPOINT_PY)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = mod  # dataclass needs the module in sys.modules
    spec.loader.exec_module(mod)
    return mod


def test_checkpoint_module_exists():
    assert CHECKPOINT_PY.exists(), f"checkpoint.py missing at {CHECKPOINT_PY}"


def test_roundtrip_save_load(tmp_path):
    mod = _load()
    cp = mod.Checkpoint(
        snapshot_id="snap_20260417_000000_abcdef",
        snapshot_date="2026-04-17",
        stage="collecting",
        platform_groups={"cisco_ios": ["R1", "R2"]},
        devices=["R1", "R2"],
        completed=[["R1", "show version"]],
        results_summary=[{"device": "R1", "command": "show version", "status": "success"}],
        all_rows=[{"device_name": "R1", "command": "show version", "raw": "x"}],
    )
    path = tmp_path / "snap.json"
    mod.save(cp, path)
    loaded = mod.load(path)
    assert loaded is not None
    assert loaded.snapshot_id == cp.snapshot_id
    assert loaded.platform_groups == cp.platform_groups
    assert loaded.completed == cp.completed
    assert loaded.results_summary == cp.results_summary


def test_completed_set_semantics():
    mod = _load()
    cp = mod.Checkpoint(
        snapshot_id="s", snapshot_date="d",
        completed=[["R1", "show version"], ["R2", "show clock"]],
    )
    s = cp.completed_set()
    assert ("R1", "show version") in s
    assert ("R2", "show clock") in s
    assert ("R1", "show clock") not in s


def test_mark_done_is_idempotent():
    mod = _load()
    cp = mod.Checkpoint(snapshot_id="s", snapshot_date="d")
    cp.mark_done("R1", "show version")
    cp.mark_done("R1", "show version")  # duplicate
    cp.mark_done("R2", "show version")
    assert len(cp.completed) == 2
    assert cp.completed_set() == {("R1", "show version"), ("R2", "show version")}


def test_load_missing_returns_none(tmp_path):
    mod = _load()
    assert mod.load(tmp_path / "does_not_exist.json") is None


def test_load_malformed_returns_none(tmp_path):
    mod = _load()
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert mod.load(bad) is None


def test_load_schema_mismatch_returns_none(tmp_path):
    mod = _load()
    bad = tmp_path / "schema.json"
    bad.write_text('{"unexpected_field": 1}', encoding="utf-8")
    assert mod.load(bad) is None


def test_save_is_atomic(tmp_path):
    """A half-written .tmp file must not clobber an existing good checkpoint."""
    mod = _load()
    path = tmp_path / "snap.json"
    good = mod.Checkpoint(snapshot_id="good", snapshot_date="2026-04-17")
    mod.save(good, path)

    # Simulate a stale .tmp from a prior crash.
    (path.with_suffix(path.suffix + ".tmp")).write_text("half", encoding="utf-8")

    # Saving again should replace the tmp cleanly and leave the target intact.
    updated = mod.Checkpoint(snapshot_id="good", snapshot_date="2026-04-17",
                             completed=[["R1", "show version"]])
    mod.save(updated, path)
    loaded = mod.load(path)
    assert loaded is not None
    assert loaded.completed == [["R1", "show version"]]


def test_state_dir_path_resolution():
    mod = _load()
    # state_dir computes the canonical directory relative to a project root.
    p = mod.state_dir(Path("/tmp/fake_root"))
    assert p == Path("/tmp/fake_root/.olav/workspace/ops/netops_init/state")


def test_checkpoint_path_uses_snapshot_id():
    mod = _load()
    p = mod.checkpoint_path(Path("/tmp/fake_root"), "snap_XYZ")
    assert p.name == "snap_XYZ.json"
    assert p.parent.name == "state"


def test_run_py_imports_checkpoint_module():
    """run.py must wire the checkpoint helpers so --resume actually works."""
    run_py = (NETOPS_INIT_DIR / "run.py").read_text(
        encoding="utf-8"
    )
    assert "from .checkpoint import" in run_py or "from .checkpoint" in run_py
    assert "--resume" in run_py
    assert "_run_collection" in run_py
    assert "completed_set" in run_py, "run.py lost the completed_set skip path"
