"""API Operation Policy — TDD tests for API-RW-1 and API-RW-2.

Covers:
1.  ApiOperationPolicy and derive_operation_policy importable
2.  GET → intent="read", approval_policy="none"
3.  POST → intent="write", approval_policy="required"
4.  PUT → intent="write", idempotent=True
5.  DELETE → side_effect_risk="high"
6.  Unknown method → intent="unknown", approval_policy="required"
7.  x-olav-intent="read" on POST → intent="read"
8.  x-olav-approval="none" on POST → approval_policy="none"
9.  source_of_truth="openapi_extension" when vendor ext used
10. Empty operationId → synthesized from method+path
11. Provided operationId is preserved
12. Full spec with multiple paths → correct number of policies
13. Spec with x-olav-intent → policy reflects override
14. dry_run return dict contains "operation_policies"
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_api_operation_policy_importable() -> None:
    from olav.core.api_operation_policy import ApiOperationPolicy, derive_operation_policy

    assert ApiOperationPolicy is not None
    assert callable(derive_operation_policy)


def test_get_defaults_to_read_intent() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(domain="platform", path="/devices", method="GET")
    assert policy.intent == "read"
    assert policy.approval_policy == "none"
    assert policy.idempotent is True
    assert policy.side_effect_risk == "low"
    assert policy.source_of_truth == "method_default"


def test_post_defaults_to_write_intent() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(domain="platform", path="/devices", method="POST")
    assert policy.intent == "write"
    assert policy.approval_policy == "required"
    assert policy.idempotent is False
    assert policy.side_effect_risk == "medium"


def test_put_defaults_to_write_intent() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(domain="platform", path="/devices/{id}", method="PUT")
    assert policy.intent == "write"
    assert policy.approval_policy == "required"
    assert policy.idempotent is True


def test_delete_defaults_to_high_risk() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(domain="netops", path="/devices/{id}", method="DELETE")
    assert policy.intent == "write"
    assert policy.side_effect_risk == "high"
    assert policy.idempotent is True
    assert policy.approval_policy == "required"


def test_unknown_method_conservative() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(domain="platform", path="/rpc", method="PURGE")
    assert policy.intent == "unknown"
    assert policy.approval_policy == "required"
    assert policy.idempotent is False
    assert policy.side_effect_risk == "medium"


def test_vendor_extension_overrides_intent() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(
        domain="platform",
        path="/devices/sync",
        method="POST",
        vendor_extensions={"x-olav-intent": "read"},
    )
    assert policy.intent == "read"
    assert policy.approval_policy == "none"


def test_vendor_extension_overrides_approval() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(
        domain="platform",
        path="/devices/sync",
        method="POST",
        vendor_extensions={"x-olav-approval": "none"},
    )
    assert policy.intent == "write"
    assert policy.approval_policy == "none"


def test_vendor_extension_sets_source_openapi() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(
        domain="platform",
        path="/devices/sync",
        method="POST",
        vendor_extensions={"x-olav-intent": "read"},
    )
    assert policy.source_of_truth == "openapi_extension"


def test_operation_id_synthesized() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(
        domain="platform",
        path="/api/v1/devices/{id}",
        method="GET",
    )
    assert policy.operation_id == "get_api_v1_devices_id"


def test_operation_id_preserved() -> None:
    from olav.core.api_operation_policy import derive_operation_policy

    policy = derive_operation_policy(
        domain="platform",
        path="/devices",
        method="GET",
        operation_id="listDevices",
    )
    assert policy.operation_id == "listDevices"


def _make_spec(**extra_op_fields: object) -> dict:
    """Build a minimal OpenAPI spec for testing."""
    spec: dict = {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0"},
        "paths": {
            "/devices": {
                "get": {"operationId": "listDevices", "responses": {"200": {"description": "ok"}}},
                "post": {
                    "operationId": "createDevice",
                    "responses": {"201": {"description": "created"}},
                },
            },
            "/devices/{id}": {
                "delete": {
                    "operationId": "deleteDevice",
                    "responses": {"200": {"description": "ok"}},
                },
            },
        },
    }
    for key, val in extra_op_fields.items():
        spec["paths"]["/devices"]["post"][key] = val
    return spec


def test_extract_operation_policies_from_spec() -> None:
    import sys

    sys.path.insert(
        0,
        str(
            Path(__file__).resolve().parents[2]
            / ".olav"
            / "workspace"
            / "config"
            / "discovery"
            / "tools"
        ),
    )
    from register_api_schema import extract_operation_policies

    spec = _make_spec()
    policies = extract_operation_policies(spec, domain="platform")
    assert len(policies) == 3
    methods = {p.method for p in policies}
    assert methods == {"get", "post", "delete"}


def test_extract_operation_policies_reads_vendor_extensions() -> None:
    import sys

    sys.path.insert(
        0,
        str(
            Path(__file__).resolve().parents[2]
            / ".olav"
            / "workspace"
            / "config"
            / "discovery"
            / "tools"
        ),
    )
    from register_api_schema import extract_operation_policies

    spec = _make_spec(**{"x-olav-intent": "read"})
    policies = extract_operation_policies(spec, domain="platform")
    post_policy = [p for p in policies if p.method == "post"][0]
    assert post_policy.intent == "read"
    assert post_policy.source_of_truth == "openapi_extension"


def test_register_api_schema_dry_run_includes_policies() -> None:
    import sys

    sys.path.insert(
        0,
        str(
            Path(__file__).resolve().parents[2]
            / ".olav"
            / "workspace"
            / "config"
            / "discovery"
            / "tools"
        ),
    )
    from register_api_schema import register_api_schema

    spec = _make_spec()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(spec, f)
        f.flush()
        result = register_api_schema(f.name, domain="platform", dry_run=True)

    assert "operation_policies" in result
    assert isinstance(result["operation_policies"], list)
    assert len(result["operation_policies"]) == 3

    post_policy = [p for p in result["operation_policies"] if p["method"] == "post"][0]
    assert post_policy["intent"] == "write"
    assert post_policy["approval_policy"] == "required"

    get_policy = [p for p in result["operation_policies"] if p["method"] == "get"][0]
    assert get_policy["intent"] == "read"
    assert get_policy["approval_policy"] == "none"
