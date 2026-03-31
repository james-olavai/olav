"""SchemaMutationService apply/approval flow tests.

Tests the full lifecycle:
  stage → list_pending → approve → apply → verify in DuckDB
"""

import json
import tempfile
from pathlib import Path

import duckdb
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(tmp_path: Path):
    from olav.core.schema_mutation_service import SchemaMutationService

    return SchemaMutationService(staging_dir=tmp_path)


def _make_request(mutation_type: str = "upsert_mapping", **kwargs):
    from olav.core.schema_mutation_service import SchemaMutationRequest

    defaults = dict(
        domain="netops",
        mutation_type=mutation_type,
        target="mapping_rules",
        payload={
            "src_field": "PEER",
            "oc_path": "bgp_neighbor",
            "vendor": "test",
            "command": "test_cmd",
        },
        requested_by="test",
    )
    defaults.update(kwargs)
    return SchemaMutationRequest(**defaults)


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------


def test_list_pending_returns_empty_when_no_staging_file(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    assert service.list_pending() == []


def test_list_pending_returns_staged_requests(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    r1 = _make_request()
    r2 = _make_request(
        mutation_type="append_evolution",
        target="pending_schema_evolutions",
        payload={"cluster_id": "c1", "proposal": "peer_asn"},
    )
    service.stage_requests([r1, r2])

    pending = service.list_pending()
    assert len(pending) == 2
    assert pending[0]["mutation_type"] == "upsert_mapping"
    assert pending[1]["mutation_type"] == "append_evolution"


def test_list_pending_shows_status_field(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    service.stage_request(_make_request())
    pending = service.list_pending()
    assert pending[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# approve_request
# ---------------------------------------------------------------------------


def test_approve_request_moves_to_approved_file(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    req = _make_request()
    service.stage_request(req)

    result = service.approve_request(req.request_id)
    assert result["status"] == "approved"

    # Approved file should now contain the request
    approved_file = tmp_path / "schema_mutations.approved.jsonl"
    assert approved_file.exists()
    approved = [json.loads(line) for line in approved_file.read_text().splitlines()]
    assert any(r["request_id"] == req.request_id for r in approved)


def test_approve_request_removes_from_pending(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    req = _make_request()
    service.stage_request(req)
    service.approve_request(req.request_id)

    pending = service.list_pending()
    assert not any(r["request_id"] == req.request_id for r in pending)


def test_approve_request_raises_for_unknown_id(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    service.stage_request(_make_request())
    with pytest.raises(KeyError):
        service.approve_request("nonexistent-id")


# ---------------------------------------------------------------------------
# apply_pending
# ---------------------------------------------------------------------------


def _init_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Bootstrap the target tables that apply_pending writes into."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mapping_rules (
            vendor      VARCHAR,
            command     VARCHAR,
            src_field   VARCHAR,
            oc_path     VARCHAR NOT NULL,
            confidence  VARCHAR,
            PRIMARY KEY (vendor, command, src_field)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_catalog (
            source_type TEXT,
            source_name TEXT,
            platform    TEXT,
            fields      TEXT,
            description TEXT,
            updated_at  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_schema_evolutions (
            evolution_id  VARCHAR PRIMARY KEY,
            cluster_id    VARCHAR,
            proposal      VARCHAR,
            domain        VARCHAR,
            created_at    TIMESTAMPTZ DEFAULT now()
        )
    """)


def test_apply_upsert_mapping(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    req = _make_request(
        mutation_type="upsert_mapping",
        payload={
            "platform": "test",
            "source_name": "test_cmd",
            "fields": [{"name": "PEER", "openconfig_path": "bgp_neighbor"}],
        },
    )
    service.stage_request(req)
    service.approve_request(req.request_id)

    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    _init_db(conn)
    result = service.apply_approved(conn)

    assert result["applied"] >= 1
    row = conn.execute(
        "SELECT fields FROM schema_catalog WHERE platform='test' AND source_name='test_cmd'"
    ).fetchone()
    assert row is not None
    fields = json.loads(row[0])
    assert any(
        f.get("name") == "PEER" and f.get("openconfig_path") == "bgp_neighbor" for f in fields
    )
    conn.close()


def test_apply_append_evolution(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    req = _make_request(
        mutation_type="append_evolution",
        target="pending_schema_evolutions",
        payload={"cluster_id": "c1", "proposal": "peer_asn"},
    )
    service.stage_request(req)
    service.approve_request(req.request_id)

    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    _init_db(conn)
    service.apply_approved(conn)

    row = conn.execute(
        "SELECT proposal FROM pending_schema_evolutions WHERE cluster_id='c1'"
    ).fetchone()
    assert row is not None
    assert row[0] == "peer_asn"
    conn.close()


def test_apply_replace_view(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    req = _make_request(
        mutation_type="replace_view",
        target="v_test_view",
        payload={"sql": "SELECT 1 AS x"},
    )
    service.stage_request(req)
    service.approve_request(req.request_id)

    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    _init_db(conn)
    service.apply_approved(conn)

    # The view should be queryable
    row = conn.execute("SELECT x FROM v_test_view").fetchone()
    assert row is not None
    assert row[0] == 1
    conn.close()


def test_apply_approved_clears_approved_file(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    req = _make_request()
    service.stage_request(req)
    service.approve_request(req.request_id)

    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    _init_db(conn)
    service.apply_approved(conn)
    conn.close()

    # After apply, approved file should be empty (or not exist)
    approved_file = tmp_path / "schema_mutations.approved.jsonl"
    if approved_file.exists():
        assert approved_file.read_text().strip() == ""


def test_apply_approved_returns_zero_when_nothing_pending(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    _init_db(conn)
    result = service.apply_approved(conn)
    conn.close()
    assert result["applied"] == 0
