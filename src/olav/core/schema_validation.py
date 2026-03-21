"""Pydantic validation + LLM self-heal loop (OC-5).

Validates mapped network data against OpenConfig Pydantic models.
On ValidationError, feeds the error back to LLM for auto-correction.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from olav.core.models.openconfig import (
    BgpNeighbor,
    Component,
    Interface,
    LldpInterface,
    OspfAreaState,
)

logger = logging.getLogger(__name__)

DOMAIN_MODELS: dict[str, type] = {
    "interface": Interface,
    "bgp_neighbor": BgpNeighbor,
    "lldp_interface": LldpInterface,
    "ospf_area": OspfAreaState,
    "component": Component,
}


def validate_and_heal(
    data: dict[str, Any],
    domain: str,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Validate *data* against the Pydantic model for *domain*.

    On failure, attempts LLM self-heal up to *max_retries* times.

    Returns
    -------
    dict with keys:
        ``valid``   — bool
        ``data``    — validated (possibly healed) dict, or original on total failure
        ``healed``  — True if LLM corrected the data
        ``errors``  — list of error strings (only if valid=False)
    """
    model_cls = DOMAIN_MODELS[domain]

    result = _try_validate(model_cls, data)
    if result is not None:
        return {"valid": True, "data": result, "healed": False}

    if max_retries <= 0:
        try:
            model_cls.model_validate(data)
        except ValidationError as exc:
            return {
                "valid": False,
                "data": data,
                "healed": False,
                "errors": [str(e) for e in exc.errors()],
            }

    last_errors: list[str] = []
    current_data = data
    for _attempt in range(max_retries):
        try:
            model_cls.model_validate(current_data)
        except ValidationError as exc:
            last_errors = [str(e) for e in exc.errors()]
            error_text = str(exc)
        else:
            break

        healed = _llm_heal(current_data, domain, error_text)
        if healed is None:
            continue

        validated = _try_validate(model_cls, healed)
        if validated is not None:
            return {"valid": True, "data": validated, "healed": True}
        current_data = healed

    return {
        "valid": False,
        "data": data,
        "healed": False,
        "errors": last_errors,
    }


def _try_validate(model_cls: type, data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        instance = model_cls.model_validate(data)
        return instance.model_dump(by_alias=True)
    except ValidationError:
        return None


def _llm_heal(
    data: dict[str, Any],
    domain: str,
    error_text: str,
) -> dict[str, Any] | None:
    try:
        from olav.core.llm import LLMFactory

        llm = LLMFactory.get_chat_model(agent_id="schema_engine")
        prompt = (
            f"The following JSON data for OpenConfig domain '{domain}' "
            f"failed Pydantic validation:\n\n"
            f"Data: {json.dumps(data)}\n\n"
            f"Validation error:\n{error_text}\n\n"
            "Fix the JSON to pass validation. "
            "Respond with ONLY the corrected JSON, no explanation."
        )
        response = llm.invoke(prompt)
        content = getattr(response, "content", str(response)).strip()
        return json.loads(content)
    except Exception as exc:
        logger.warning("LLM heal failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# OC-15: Dynamic YANG validation via yangson
# ---------------------------------------------------------------------------


def validate_with_yangson(
    data: dict[str, Any],
    yang_text: str,
    yang_library: dict[str, Any],
) -> dict[str, Any]:
    """Validate *data* against a YANG schema using yangson (OC-15).

    This is an additive validation layer on top of Pydantic (OC-5).  It uses
    the yangson ``DataModel`` to perform RFC 7950 type/constraint checking
    against an arbitrary YANG module supplied as raw text.

    Parameters
    ----------
    data:
        The record to validate — a namespace-qualified dict matching the
        YANG module structure (e.g. ``{"module:container": {...}}``).
    yang_text:
        Full YANG module source text for the relevant module.
    yang_library:
        YANG Library dict (RFC 7895 / ietf-yang-library) that describes the
        module metadata.  Must contain ``ietf-yang-library:modules-state``.

    Returns
    -------
    dict with keys:
        ``valid``  — bool
        ``errors`` — list of error strings (empty on success)
    """
    try:
        import json as _json
        import os
        import tempfile

        from yangson.datamodel import DataModel
        from yangson.enumerations import ContentType, ValidationScope

        yl_text = _json.dumps(yang_library)

        # Extract module name from yang_library for the temp file name.
        modules = yang_library.get("ietf-yang-library:modules-state", {}).get("module", [])
        module_name = modules[0]["name"] if modules else "unknown"

        with tempfile.TemporaryDirectory() as tmpdir:
            yang_file = os.path.join(tmpdir, f"{module_name}.yang")
            with open(yang_file, "w", encoding="utf-8") as fh:
                fh.write(yang_text)

            dm = DataModel(yl_text, mod_path=[tmpdir])
            inst = dm.from_raw(data)
            inst.validate(ValidationScope.all, ContentType.config)

        return {"valid": True, "errors": []}

    except Exception as exc:
        return {"valid": False, "errors": [str(exc)]}
