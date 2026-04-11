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
"""

from __future__ import annotations


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
