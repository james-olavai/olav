"""Schema Engine Phase 1 — guard tests.

Covers:
1. build_semantic_summary() produces a deterministic pipe-delimited string
2. classify_field() returns unclassified when embedder unavailable (graceful)
3. classify_field() returns matched when vector confidence > 0.85 (mock)
4. classify_field() returns llm_confirmed when confidence in [0.60, 0.85] (mock)
5. classify_field() returns unclassified when confidence < 0.60 (mock)
6. save_mapping() builds a correct SchemaMutationRequest (upsert_mapping type)
7. create_unified_view() generates valid CREATE OR REPLACE VIEW SQL
8. build_mutation_request() is importable and returns a SchemaMutationRequest
9. SchemaEngine class exists and can be instantiated with a mutation_service
10. classify_field() uses LanceDB table named <domain>_field_mappings

Note: As of OC-17, all schema mappings are stored in the ``mapping_rules`` table.
``openconfig_path`` is the canonical OC path field throughout the schema engine.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. build_semantic_summary
# ---------------------------------------------------------------------------


def test_build_semantic_summary_basic() -> None:
    from olav.core.schema_engine import build_semantic_summary

    field = {
        "name": "ip_address",
        "description": "IPv4 management address",
        "type": "string",
        "example": "192.168.1.1",
        "command": "show interfaces",
    }
    result = build_semantic_summary(field)
    assert "ip_address" in result
    assert "IPv4 management address" in result
    assert "show interfaces" in result
    assert " | " in result


def test_build_semantic_summary_skips_empty_parts() -> None:
    from olav.core.schema_engine import build_semantic_summary

    field = {"name": "bgp_peer", "description": "", "type": "string"}
    result = build_semantic_summary(field)
    # Empty description → not included; no leading/trailing " | "
    assert not result.startswith(" | ")
    assert not result.endswith(" | ")
    assert "bgp_peer" in result


def test_build_semantic_summary_all_empty() -> None:
    from olav.core.schema_engine import build_semantic_summary

    result = build_semantic_summary({})
    assert result == ""


# ---------------------------------------------------------------------------
# 2–5. classify_field() — confidence dispatch (embedder mocked)
# ---------------------------------------------------------------------------


def test_classify_field_requires_embedder_in_strict_mode() -> None:
    from olav.core.schema_engine import SchemaEngine
    from olav.core.schema_mutation_service import SchemaMutationService

    svc = MagicMock(spec=SchemaMutationService)
    engine = SchemaEngine(mutation_service=svc, embedder=None)

    with pytest.raises(RuntimeError, match="requires an embedder"):
        engine.classify_field({"name": "x", "domain": "netops"})


def _make_engine_with_mock_vector(distance: float, openconfig_path: str = "management_ip"):
    """Helper: build SchemaEngine with a mock embedder and LanceDB table."""
    from olav.core.schema_engine import SchemaEngine
    from olav.core.schema_mutation_service import SchemaMutationService

    svc = MagicMock(spec=SchemaMutationService)

    mock_embedder = MagicMock()
    mock_vector_result = MagicMock()
    mock_vector_result.tolist.return_value = [0.1] * 384
    mock_embedder.encode.return_value = mock_vector_result

    mock_table = MagicMock()
    mock_table.search.return_value.limit.return_value.to_list.return_value = [
        {"_distance": distance, "openconfig_path": openconfig_path}
    ]

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table

    engine = SchemaEngine(mutation_service=svc, embedder=mock_embedder, _lancedb_override=mock_db)
    return engine, svc


def test_classify_field_matched_high_confidence() -> None:
    engine, svc = _make_engine_with_mock_vector(distance=0.1)  # confidence = 0.95
    result = engine.classify_field({"name": "ip_address", "domain": "netops"})
    assert result["status"] == "matched"
    assert result["openconfig_path"] == "management_ip"
    assert result["confidence"] > 0.85
    svc.stage_request.assert_called_once()


def test_classify_field_llm_confirmed_mid_confidence() -> None:
    engine, svc = _make_engine_with_mock_vector(distance=0.5)  # confidence = 0.75

    with patch.object(engine, "_llm_confirm", return_value="management_ip") as mock_llm:
        result = engine.classify_field({"name": "mgmt_ip", "domain": "netops"})
    assert result["status"] == "llm_confirmed"
    assert result["confidence"] >= 0.60
    assert result["confidence"] <= 0.85
    mock_llm.assert_called_once()
    svc.stage_request.assert_called_once()


def test_classify_field_unclassified_low_confidence() -> None:
    engine, svc = _make_engine_with_mock_vector(distance=1.5)  # confidence = 0.25
    result = engine.classify_field({"name": "xyzfield", "domain": "netops"})
    assert result["status"] == "unclassified"
    assert result["confidence"] < 0.60
    # should stage an append_evolution request
    svc.stage_request.assert_called_once()


def test_classify_field_uses_domain_table_name() -> None:
    from olav.core.schema_engine import SchemaEngine
    from olav.core.schema_mutation_service import SchemaMutationService

    svc = MagicMock(spec=SchemaMutationService)
    mock_embedder = MagicMock()
    mock_vector_result = MagicMock()
    mock_vector_result.tolist.return_value = [0.0] * 384
    mock_embedder.encode.return_value = mock_vector_result

    mock_db = MagicMock()
    mock_db.open_table.return_value.search.return_value.limit.return_value.to_list.return_value = []

    engine = SchemaEngine(mutation_service=svc, embedder=mock_embedder, _lancedb_override=mock_db)
    engine.classify_field({"name": "x", "domain": "myapp"})

    mock_db.open_table.assert_called_with("myapp_field_mappings")


# ---------------------------------------------------------------------------
# 6. save_mapping() → SchemaMutationRequest of type upsert_mapping
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="Phase 2 quarantine: contradicts doc 07/08 target contracts")
def test_save_mapping_builds_upsert_request() -> None:
    from olav.core.schema_engine import SchemaEngine
    from olav.core.schema_mutation_service import SchemaMutationService, SchemaMutationRequest

    svc = MagicMock(spec=SchemaMutationService)
    engine = SchemaEngine(mutation_service=svc, embedder=None)

    engine.save_mapping(
        field_metadata={"name": "ip_address", "domain": "netops", "command": "show interfaces"},
        openconfig_path="management_ip",
        method="vector",
    )

    svc.stage_request.assert_called_once()
    req = svc.stage_request.call_args[0][0]
    assert isinstance(req, SchemaMutationRequest)
    assert req.mutation_type == "upsert_mapping"
    assert req.payload["openconfig_path"] == "management_ip"
    assert req.payload["method"] == "vector"


# ---------------------------------------------------------------------------
# 7. create_unified_view() SQL generation
# ---------------------------------------------------------------------------


def test_create_unified_view_generates_sql() -> None:
    from olav.core.schema_engine import create_unified_view

    mappings = [
        {"raw_key": "IP_ADDRESS", "openconfig_path": "management_ip", "data_type": "VARCHAR"},
        {"raw_key": "INTERFACE", "openconfig_path": "interface_name", "data_type": "VARCHAR"},
    ]
    sql = create_unified_view("show interfaces", mappings)
    assert "CREATE OR REPLACE VIEW" in sql
    assert "v_unified_show_interfaces" in sql
    assert "management_ip" in sql
    assert "interface_name" in sql
    assert "TRY_CAST" in sql


def test_create_unified_view_sanitizes_command_name() -> None:
    from olav.core.schema_engine import create_unified_view

    sql = create_unified_view("show ip bgp neighbors", [])
    assert "v_unified_show_ip_bgp_neighbors" in sql
    assert " " not in sql.split("VIEW")[1].split("AS")[0].strip()


# ---------------------------------------------------------------------------
# 8. build_mutation_request() importable
# ---------------------------------------------------------------------------


def test_build_mutation_request_importable() -> None:
    from olav.core.schema_engine import build_mutation_request
    from olav.core.schema_mutation_service import SchemaMutationRequest

    req = build_mutation_request(
        domain="netops",
        mutation_type="upsert_mapping",
        target="mapping_rules",
        payload={"raw_key": "X", "openconfig_path": "y"},
    )
    assert isinstance(req, SchemaMutationRequest)
    assert req.domain == "netops"
    assert req.mutation_type == "upsert_mapping"


# ---------------------------------------------------------------------------
# 9. SchemaEngine class instantiation
# ---------------------------------------------------------------------------


def test_schema_engine_instantiable() -> None:
    from olav.core.schema_engine import SchemaEngine
    from olav.core.schema_mutation_service import SchemaMutationService

    svc = MagicMock(spec=SchemaMutationService)
    engine = SchemaEngine(mutation_service=svc)
    assert engine is not None
