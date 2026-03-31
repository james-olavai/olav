import json
from pathlib import Path


def test_schema_mutation_service_stages_request_as_jsonl(tmp_path: Path) -> None:
    from olav.core.schema_mutation_service import SchemaMutationRequest, SchemaMutationService

    service = SchemaMutationService(staging_dir=tmp_path)
    request = SchemaMutationRequest(
        domain="netops",
        mutation_type="upsert_mapping",
        target="mapping_rules",
        payload={"raw_key": "PEER", "openconfig_path": "bgp_neighbor"},
        requested_by="config.discovery",
    )

    result = service.stage_request(request)

    assert result["status"] == "staged"
    assert result["requests_staged"] == 1
    assert result["staging_file"].endswith("schema_mutations.pending.jsonl")

    staging_file = tmp_path / "schema_mutations.pending.jsonl"
    lines = staging_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    staged_request = json.loads(lines[0])
    assert staged_request["domain"] == "netops"
    assert staged_request["mutation_type"] == "upsert_mapping"
    assert staged_request["target"] == "mapping_rules"
    assert staged_request["payload"]["openconfig_path"] == "bgp_neighbor"
    assert staged_request["requested_by"] == "config.discovery"


def test_schema_mutation_service_rejects_empty_payload(tmp_path: Path) -> None:
    from olav.core.schema_mutation_service import SchemaMutationRequest, SchemaMutationService

    service = SchemaMutationService(staging_dir=tmp_path)
    request = SchemaMutationRequest(
        domain="platform",
        mutation_type="replace_view",
        target="v_unified_interfaces",
        payload={},
    )

    try:
        service.stage_request(request)
    except ValueError as exc:
        assert "payload" in str(exc)
    else:
        raise AssertionError("Expected ValueError for empty payload")


def test_schema_mutation_service_stages_multiple_requests(tmp_path: Path) -> None:
    from olav.core.schema_mutation_service import SchemaMutationRequest, SchemaMutationService

    service = SchemaMutationService(staging_dir=tmp_path)
    requests = [
        SchemaMutationRequest(
            domain="netops",
            mutation_type="upsert_mapping",
            target="mapping_rules",
            payload={"raw_key": "PEER", "openconfig_path": "bgp_neighbor"},
        ),
        SchemaMutationRequest(
            domain="netops",
            mutation_type="append_evolution",
            target="pending_schema_evolutions",
            payload={"cluster_id": "cluster-1", "proposal": "peer_asn"},
        ),
    ]

    result = service.stage_requests(requests)

    assert result["status"] == "staged"
    assert result["requests_staged"] == 2
    assert (
        len((tmp_path / "schema_mutations.pending.jsonl").read_text(encoding="utf-8").splitlines())
        == 2
    )
