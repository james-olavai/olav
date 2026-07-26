"""Governance gate for the tiered DuckDB write-concurrency boundary (ADR-0018/0019).

Pins the OSS↔Enterprise seam invariants introduced by the write-concurrency work
(dev_docs/111):

1. The OSS seam (``olav.core.db_write``) must NOT hard-import ``olav.enterprise``
   at module level — the cross-process flock queue is enterprise-only and is
   injected via a *guarded* import inside ``_cross_process_gate``. A module-level
   import would break every plain (OSS) install with ``ModuleNotFoundError``.
2. ``open_write_connection`` must function with no enterprise gate present
   (OSS behaviour = ``nullcontext`` + retry).
3. The flock *queue implementation* (``fcntl``) must live only in
   ``olav.enterprise`` (shipped by olav-ent), never in the OSS ``src/olav`` tree.
   Personal-tier stays retry-only; queuing is a team-tier (enterprise) feature.
"""

from __future__ import annotations

import ast
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
OSS_ROOT = REPO / "src" / "olav"
DB_WRITE = OSS_ROOT / "core" / "db_write.py"


def _iter_oss_py() -> list[Path]:
    out: list[Path] = []
    for py in OSS_ROOT.rglob("*.py"):
        s = str(py)
        if "node_modules" in s or f"{Path('/')}web{Path('/')}" in s or "/web/" in s:
            continue
        out.append(py)
    return out


def test_seam_does_not_hard_import_enterprise() -> None:
    """The enterprise gate import must stay guarded (inside a function), never
    a module-level import of olav.enterprise in the seam."""
    tree = ast.parse(DB_WRITE.read_text())
    for node in tree.body:  # module-level statements only
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        for n in names:
            assert not n.startswith("olav.enterprise"), (
                f"db_write.py imports {n!r} at module level — the enterprise "
                "flock gate must be a guarded import inside _cross_process_gate "
                "(ADR-0019). A hard import breaks plain OSS installs."
            )


def test_seam_works_without_enterprise_gate(tmp_path, monkeypatch) -> None:
    """open_write_connection must work with no enterprise gate (OSS nullcontext)."""
    import olav.core.db_write as seam

    monkeypatch.setattr(seam, "_gate_resolved", True)
    monkeypatch.setattr(seam, "_gate_fn", None)

    db = tmp_path / "w.duckdb"
    with seam.open_write_connection(db) as conn:
        conn.execute("CREATE TABLE t (i INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
    with duckdb.connect(str(db), read_only=True) as ro:
        assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == 1


def test_no_flock_queue_impl_in_oss() -> None:
    """The cross-process flock queue (fcntl) must live only in olav.enterprise,
    never in the OSS src/olav tree — queuing is a team-tier (enterprise) feature."""
    offenders: list[str] = []
    for py in _iter_oss_py():
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue  # pre-existing unparsable file — not this gate's concern
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "fcntl" for a in node.names):
                offenders.append(str(py.relative_to(REPO)))
            elif isinstance(node, ast.ImportFrom) and node.module == "fcntl":
                offenders.append(str(py.relative_to(REPO)))
    assert not offenders, (
        "fcntl (flock queue) imported in the OSS tree — queuing must stay "
        "enterprise-only (olav.enterprise.db_write_gate): " + ", ".join(sorted(set(offenders)))
    )
