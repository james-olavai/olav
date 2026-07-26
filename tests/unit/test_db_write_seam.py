"""Unit tests for the unified DuckDB write seam (olav.core.db_write).

Covers the OSS behaviour (ADR-0018/0019 §OSS): in-process lock + connect-retry,
connection injection, read-only path, per-db-path lock isolation, and that a
non-lock error is not swallowed by the retry loop. The enterprise flock gate is
tested separately under ``olav-ent/tests``.
"""

from __future__ import annotations

import multiprocessing as mp
import threading
from pathlib import Path

import duckdb
import pytest

from olav.core.db_write import open_write_connection


def _ensure_table(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS t (i INTEGER)")


def test_basic_write_persists(tmp_path: Path) -> None:
    db = tmp_path / "w.duckdb"
    with open_write_connection(db) as conn:
        _ensure_table(conn)
        conn.execute("INSERT INTO t VALUES (1), (2)")
    with duckdb.connect(str(db), read_only=True) as ro:
        assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == 2


def test_creates_parent_dir(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "deep" / "w.duckdb"
    with open_write_connection(db) as conn:
        _ensure_table(conn)
    assert db.parent.is_dir()


def test_injected_conn_is_reused_and_not_closed(tmp_path: Path) -> None:
    db = tmp_path / "w.duckdb"
    outer = duckdb.connect(str(db))
    _ensure_table(outer)
    with open_write_connection(db, conn=outer) as conn:
        assert conn is outer
        conn.execute("INSERT INTO t VALUES (7)")
    # seam must NOT have closed a connection it did not own
    assert outer.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    outer.close()


def test_read_only_path_yields_readable_conn(tmp_path: Path) -> None:
    db = tmp_path / "w.duckdb"
    with open_write_connection(db) as conn:
        _ensure_table(conn)
        conn.execute("INSERT INTO t VALUES (5)")
    with open_write_connection(db, read_only=True) as ro:
        assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == 1


def test_non_lock_error_raises_not_retried(tmp_path: Path) -> None:
    db = tmp_path / "w.duckdb"
    with pytest.raises(duckdb.Error):
        with open_write_connection(db) as conn:
            conn.execute("SELECT * FROM does_not_exist")


def test_concurrent_threads_same_db_no_loss(tmp_path: Path) -> None:
    """In-process lock must serialise threads writing the same DB with no loss."""
    db = tmp_path / "w.duckdb"
    with open_write_connection(db) as conn:
        _ensure_table(conn)
    n_threads, per = 8, 25
    errors: list[Exception] = []

    def worker(base: int) -> None:
        try:
            for k in range(per):
                with open_write_connection(db) as conn:
                    conn.execute("INSERT INTO t VALUES (?)", [base * 1000 + k])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent writers failed: {errors}"
    with duckdb.connect(str(db), read_only=True) as ro:
        assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == n_threads * per


def test_distinct_db_paths_have_independent_locks(tmp_path: Path) -> None:
    """A held write on db A must not block a write on db B (no false serialisation)."""
    db_a = tmp_path / "a.duckdb"
    db_b = tmp_path / "b.duckdb"
    with open_write_connection(db_a) as ca:
        _ensure_table(ca)
        # While holding A's lock, B must be acquirable in the same thread.
        with open_write_connection(db_b) as cb:
            _ensure_table(cb)
            cb.execute("INSERT INTO t VALUES (1)")
        ca.execute("INSERT INTO t VALUES (1)")
    with duckdb.connect(str(db_a), read_only=True) as ro:
        assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == 1


def test_write_enters_cross_process_gate(tmp_path: Path, monkeypatch) -> None:
    """The seam must enter the injected enterprise gate on a write.

    Proves the wiring that ADR-0019 relies on: when ``olav.enterprise`` provides
    a gate, ``open_write_connection`` acquires it (once) around the write body.
    Read-only and injected-conn paths must NOT enter the gate.
    """
    import contextlib as _cl

    import olav.core.db_write as seam

    entered: list[str] = []

    @_cl.contextmanager
    def spy_gate(db_path: str):
        entered.append(db_path)
        yield

    # Simulate an enterprise install: force the resolver to our spy.
    monkeypatch.setattr(seam, "_gate_resolved", True)
    monkeypatch.setattr(seam, "_gate_fn", spy_gate)

    db = tmp_path / "w.duckdb"
    with seam.open_write_connection(db) as conn:
        _ensure_table(conn)
    assert entered == [str(db)], "write must enter the gate exactly once"

    # read-only must not gate
    entered.clear()
    with seam.open_write_connection(db, read_only=True):
        pass
    assert entered == []

    # injected conn must not gate (caller owns serialisation)
    outer = duckdb.connect(str(db))
    with seam.open_write_connection(db, conn=outer):
        pass
    outer.close()
    assert entered == []


def test_nested_owning_open_same_path_no_deadlock(tmp_path: Path) -> None:
    """A nested owning-open on the same db_path (same thread) must not deadlock,
    and both writes must persist. netops relies on this (take_snapshot/map_engine)."""
    db = tmp_path / "w.duckdb"
    with open_write_connection(db) as outer:
        _ensure_table(outer)
        outer.execute("INSERT INTO t VALUES (1)")
        # nested owning-open on the SAME path — must be reentrant, not deadlock
        with open_write_connection(db) as inner:
            assert inner is not outer
            inner.execute("INSERT INTO t VALUES (2)")
        outer.execute("INSERT INTO t VALUES (3)")
    with duckdb.connect(str(db), read_only=True) as ro:
        assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == 3


def test_nested_open_skips_gate(tmp_path: Path, monkeypatch) -> None:
    """The enterprise gate must be entered only for the OUTER open, not the nested one."""
    import contextlib as _cl

    import olav.core.db_write as seam

    entered: list[str] = []

    @_cl.contextmanager
    def spy_gate(db_path: str):
        entered.append(db_path)
        yield

    monkeypatch.setattr(seam, "_gate_resolved", True)
    monkeypatch.setattr(seam, "_gate_fn", spy_gate)

    db = tmp_path / "w.duckdb"
    with seam.open_write_connection(db) as outer:
        _ensure_table(outer)
        with seam.open_write_connection(db) as inner:
            inner.execute("CREATE TABLE IF NOT EXISTS u (i INTEGER)")
    assert entered == [str(db)], "gate must be acquired once (outer only)"


def _proc_writer(db_str: str, base: int, per: int) -> int:
    from olav.core.db_write import open_write_connection as owc

    for k in range(per):
        with owc(db_str) as conn:
            conn.execute("INSERT INTO t VALUES (?)", [base * 1000 + k])
    return per


def test_cross_process_connect_retry_survives_contention(tmp_path: Path) -> None:
    """Real subprocesses racing the same DB must all land via connect-retry.

    This is the OSS cross-process guarantee: no flock, DuckDB's file lock does
    not queue, so the seam's connect-retry is what makes concurrent processes
    converge instead of one failing at connect()."""
    db = tmp_path / "w.duckdb"
    with open_write_connection(db) as conn:
        _ensure_table(conn)
    n_proc, per = 4, 20
    ctx = mp.get_context("spawn")
    with ctx.Pool(n_proc) as pool:
        results = pool.starmap(
            _proc_writer, [(str(db), i, per) for i in range(n_proc)]
        )
    assert sum(results) == n_proc * per
    with duckdb.connect(str(db), read_only=True) as ro:
        assert ro.execute("SELECT count(*) FROM t").fetchone()[0] == n_proc * per
