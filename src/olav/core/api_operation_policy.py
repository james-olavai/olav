"""API Operation Policy — read/write intent classification for OpenAPI operations.

Design reference: dev_docs/api_discovery.md §4.5

Each registered API operation gets an ApiOperationPolicy that captures its
intent (read/write), approval requirements, and risk level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ApiOperationPolicy:
    """Policy metadata for a single API operation.

    Attributes
    ----------
    domain:           Domain namespace (e.g. "platform", "netops").
    operation_id:     OpenAPI operationId or synthesized from method+path.
    path:             API path (e.g. "/api/v1/devices").
    method:           HTTP method (lowercase: "get", "post", etc.).
    intent:           Derived intent: "read", "write", or "unknown".
    approval_policy:  "none" for reads, "required" for writes.
    idempotent:       Whether the operation is idempotent (GET/PUT/DELETE=True, POST/PATCH=False).
    side_effect_risk: Risk level: "low", "medium", "high".
    source_of_truth:  How the policy was determined.
    """

    domain: str
    operation_id: str
    path: str
    method: str
    intent: Literal["read", "write", "unknown"] = "unknown"
    approval_policy: Literal["none", "required"] = "required"
    idempotent: bool = False
    side_effect_risk: Literal["low", "medium", "high"] = "medium"
    source_of_truth: Literal["method_default", "openapi_extension", "manual_override"] = (
        "method_default"
    )


# ── Default method → intent mapping ──────────────────────────────────────────

_METHOD_DEFAULTS: dict[str, dict] = {
    "get": {
        "intent": "read",
        "approval_policy": "none",
        "idempotent": True,
        "side_effect_risk": "low",
    },
    "head": {
        "intent": "read",
        "approval_policy": "none",
        "idempotent": True,
        "side_effect_risk": "low",
    },
    "options": {
        "intent": "read",
        "approval_policy": "none",
        "idempotent": True,
        "side_effect_risk": "low",
    },
    "post": {
        "intent": "write",
        "approval_policy": "required",
        "idempotent": False,
        "side_effect_risk": "medium",
    },
    "put": {
        "intent": "write",
        "approval_policy": "required",
        "idempotent": True,
        "side_effect_risk": "medium",
    },
    "patch": {
        "intent": "write",
        "approval_policy": "required",
        "idempotent": False,
        "side_effect_risk": "medium",
    },
    "delete": {
        "intent": "write",
        "approval_policy": "required",
        "idempotent": True,
        "side_effect_risk": "high",
    },
}


def derive_operation_policy(
    domain: str,
    path: str,
    method: str,
    operation_id: str = "",
    *,
    vendor_extensions: dict | None = None,
) -> ApiOperationPolicy:
    """Derive an ApiOperationPolicy from path, method, and optional vendor extensions.

    Parameters
    ----------
    domain:            Domain namespace.
    path:              API path string.
    method:            HTTP method (case-insensitive).
    operation_id:      OpenAPI operationId or empty (will be synthesized).
    vendor_extensions: Dict with optional keys:
                       ``x-olav-intent`` → overrides intent ("read"/"write")
                       ``x-olav-approval`` → overrides approval_policy ("none"/"required")

    Returns
    -------
    ApiOperationPolicy with derived or overridden values.
    """
    method_lower = method.lower()
    defaults = _METHOD_DEFAULTS.get(
        method_lower,
        {
            "intent": "unknown",
            "approval_policy": "required",  # unknown = conservative = required
            "idempotent": False,
            "side_effect_risk": "medium",
        },
    )

    # Synthesize operation_id if not provided
    if not operation_id:
        # "/api/v1/devices/{id}" + "get" → "get_api_v1_devices_id"
        clean_path = path.replace("{", "").replace("}", "").replace("/", "_").strip("_")
        operation_id = f"{method_lower}_{clean_path}"

    intent = defaults["intent"]
    approval_policy = defaults["approval_policy"]
    source = "method_default"

    # API-RW-2: vendor extension overrides
    if vendor_extensions:
        if "x-olav-intent" in vendor_extensions:
            override_intent = vendor_extensions["x-olav-intent"]
            if override_intent in ("read", "write"):
                intent = override_intent
                # Adjust approval_policy based on overridden intent
                approval_policy = "none" if intent == "read" else "required"
                source = "openapi_extension"

        if "x-olav-approval" in vendor_extensions:
            override_approval = vendor_extensions["x-olav-approval"]
            if override_approval in ("none", "required"):
                approval_policy = override_approval
                source = "openapi_extension"

    return ApiOperationPolicy(
        domain=domain,
        operation_id=operation_id,
        path=path,
        method=method_lower,
        intent=intent,
        approval_policy=approval_policy,
        idempotent=defaults["idempotent"],
        side_effect_risk=defaults["side_effect_risk"],
        source_of_truth=source,
    )
