"""Lab-side TCF orchestration helpers.

Per ADR-0007 (Python-first tool architecture), these helpers are
the Python core that the ops-lab agent calls from
``run_python_simulation`` — replacing the MCP wrappers
``tcf_load_for_lab`` and ``tcf_record_lab_run`` that previously
lived in ``olav-netops/.olav/workspace/netops/lab/tools/``.

Return ``dict`` envelopes (not JSON strings) so callers in a
sandbox can use them directly. Sandbox callers can still
``json.dumps(envelope)`` to print a single-line result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .tcf_args import tcf_to_r88_args, tcf_to_r89_args
from .tcf_io import tcf_emit, tcf_load
from .tcf_schema import CliBlock, JournalEntry, PostCheck, StepVerdict


def tcf_load_for_lab(spec_path: str | Path) -> dict[str, Any]:
    """Load a TCF spec and derive everything the lab needs.

    Returns a dict envelope with:
      * ``status``: ``"ok"`` / ``"error"``
      * ``change_id``, ``title``, ``risk_class``, ``intent``
      * ``device_names``, ``devices``
      * ``r88_args``: kwargs for ``generate_clab_topology``
      * ``r89_args``: kwargs for ``generate_srl_lab_config``
        (``None`` if intent.type unsupported; reason in ``r89_error``)
      * ``post_check``, ``tvt``, ``required_tests``, ``optional_tests``
    """
    try:
        tcf = tcf_load(spec_path)
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "error": f"TCF file not found: {spec_path}",
            "detail": str(exc),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": f"TCF parse failed: {type(exc).__name__}: {exc}",
            "spec_path": str(spec_path),
        }

    r88_args = tcf_to_r88_args(tcf)
    try:
        r89_args = tcf_to_r89_args(tcf)
        r89_error = None
    except ValueError as exc:
        r89_args = None
        r89_error = str(exc)

    return {
        "status": "ok",
        "spec_path": str(spec_path),
        "change_id": tcf.change_id,
        "title": tcf.title,
        "risk_class": tcf.risk_class,
        "intent": tcf.intent.model_dump(),
        "device_names": [d.name for d in tcf.devices],
        "devices": [d.model_dump() for d in tcf.devices],
        "r88_args": r88_args,
        "r89_args": r89_args,
        "r89_error": r89_error,
        "post_check": [c.model_dump() for c in tcf.post_check],
        "tvt": [t.model_dump() for t in tcf.tvt],
        "required_tests": tcf.required_tests,
        "optional_tests": tcf.optional_tests,
    }


def tcf_record_lab_run(
    spec_path: str | Path,
    *,
    verdict: str,
    lab_name: str,
    snapshot_id: str = "",
    diagnosis: str = "",
    recommendation: list[str] | None = None,
    tvt_test_ids: list[str] | None = None,
    tvt_actual_lab: list[str] | None = None,
    tvt_status: list[str] | None = None,
    journal: list[dict[str, Any]] | str | None = None,
    implementation_lab: list[dict[str, Any]] | str | None = None,
    rollback_lab: list[dict[str, Any]] | str | None = None,
    post_check_lab: list[dict[str, Any]] | str | None = None,
    step_verdicts: list[dict[str, Any]] | str | None = None,
) -> dict[str, Any]:
    """Atomically write lab results back into a TCF spec.

    TVT updates use 3 parallel arrays (``tvt_test_ids`` /
    ``tvt_actual_lab`` / ``tvt_status``) — same shape as the
    flattened arrays we use elsewhere for small-model robustness.

    ``journal`` accepts either a list of dicts (preferred) or a JSON
    string (for sandbox callers that build it as text).

    R94 lab-side fields (``implementation_lab``, ``rollback_lab``,
    ``post_check_lab``, ``step_verdicts``) each accept a list of dicts
    or a JSON string and land in the matching ``ExecutionRecord``
    field. Each list element is validated against its Pydantic model
    (``CliBlock`` / ``PostCheck`` / ``StepVerdict``); errors are
    returned as structured envelopes so sandbox callers see exactly
    which row failed.

    The ``*_lab`` fields are SRL twin evidence — sim writes the real
    prod-form CLI in the top-level ``implementation[]`` /
    ``rollback[]`` / ``post_check[]`` lists; lab writes the SRL
    translation here as proof the plan works on the digital twin.
    """
    try:
        tcf = tcf_load(spec_path)
    except FileNotFoundError:
        return {"status": "error", "error": f"TCF file not found: {spec_path}"}
    except Exception as exc:
        return {
            "status": "error",
            "error": f"TCF load failed: {type(exc).__name__}: {exc}",
        }

    test_ids = list(tvt_test_ids or [])
    actuals = list(tvt_actual_lab or [])
    statuses = list(tvt_status or [])
    if not (len(test_ids) == len(actuals) == len(statuses)):
        return {
            "status": "error",
            "error": (
                f"tvt_test_ids / tvt_actual_lab / tvt_status must be same "
                f"length: got {len(test_ids)} / {len(actuals)} / {len(statuses)}"
            ),
        }

    known_ids = {row.test_id for row in tcf.tvt}
    unknown = [tid for tid in test_ids if tid not in known_ids]
    if unknown:
        return {
            "status": "error",
            "error": (
                f"unknown test_ids in tvt update: {unknown}. "
                f"Known: {sorted(known_ids)}"
            ),
        }

    if journal is None:
        journal_raw: list[Any] = []
    elif isinstance(journal, str):
        try:
            journal_raw = json.loads(journal) if journal else []
        except json.JSONDecodeError as exc:
            return {"status": "error", "error": f"journal is not valid JSON: {exc}"}
    else:
        journal_raw = list(journal)

    if not isinstance(journal_raw, list):
        return {
            "status": "error",
            "error": f"journal must be a list; got {type(journal_raw).__name__}",
        }

    journal_entries: list[JournalEntry] = []
    for i, raw in enumerate(journal_raw):
        if not isinstance(raw, dict):
            return {
                "status": "error",
                "error": f"journal[{i}] must be an object; got {type(raw).__name__}",
            }
        try:
            journal_entries.append(JournalEntry(**raw))
        except Exception as exc:
            return {
                "status": "error",
                "error": f"journal[{i}] invalid: {type(exc).__name__}: {exc}",
            }

    update_map = dict(zip(test_ids, zip(actuals, statuses, strict=True), strict=True))
    updated_count = 0
    for row in tcf.tvt:
        if row.test_id in update_map:
            actual, status = update_map[row.test_id]
            row.actual_lab = actual
            row.status = status
            updated_count += 1

    impl_parse = _parse_model_list(
        implementation_lab, CliBlock, "implementation_lab"
    )
    if "error" in impl_parse:
        return impl_parse
    rb_parse = _parse_model_list(rollback_lab, CliBlock, "rollback_lab")
    if "error" in rb_parse:
        return rb_parse
    pc_parse = _parse_model_list(post_check_lab, PostCheck, "post_check_lab")
    if "error" in pc_parse:
        return pc_parse
    sv_parse = _parse_model_list(step_verdicts, StepVerdict, "step_verdicts")
    if "error" in sv_parse:
        return sv_parse

    tcf.lab.verdict = verdict
    tcf.lab.lab_name = lab_name or None
    tcf.lab.snapshot_id = snapshot_id or None
    tcf.lab.ran_at = datetime.now(UTC)
    tcf.lab.journal = journal_entries
    tcf.lab.diagnosis = diagnosis
    tcf.lab.recommendation = list(recommendation or [])
    tcf.lab.implementation_lab = impl_parse["items"]
    tcf.lab.rollback_lab = rb_parse["items"]
    tcf.lab.post_check_lab = pc_parse["items"]
    tcf.lab.step_verdicts = sv_parse["items"]

    try:
        out = tcf_emit(tcf, spec_path)
    except Exception as exc:
        return {
            "status": "error",
            "error": f"TCF emit failed: {type(exc).__name__}: {exc}",
        }

    return {
        "status": "ok",
        "spec_path": str(out),
        "verdict": verdict,
        "updated_tvt": updated_count,
        "journal_entries": len(journal_entries),
        "lab_name": lab_name,
        "implementation_lab_blocks": len(impl_parse["items"]),
        "rollback_lab_blocks": len(rb_parse["items"]),
        "post_check_lab_entries": len(pc_parse["items"]),
        "step_verdicts": len(sv_parse["items"]),
    }


def _parse_model_list(
    raw: list[dict[str, Any]] | str | None,
    model_cls: type,
    field_name: str,
) -> dict[str, Any]:
    """Parse a list of dicts (or JSON string) into Pydantic instances.

    Returns ``{"items": list}`` on success or ``{"status": "error",
    "error": str}`` on failure. Mirrors the journal parsing flow so
    sandbox callers see consistent error envelopes.
    """
    if raw is None:
        return {"items": []}
    if isinstance(raw, str):
        if not raw:
            return {"items": []}
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {
                "status": "error",
                "error": f"{field_name} is not valid JSON: {exc}",
            }
    if not isinstance(raw, list):
        return {
            "status": "error",
            "error": (
                f"{field_name} must be a list; got {type(raw).__name__}"
            ),
        }
    items: list[Any] = []
    for i, entry in enumerate(raw):
        if isinstance(entry, model_cls):
            items.append(entry)
            continue
        if not isinstance(entry, dict):
            return {
                "status": "error",
                "error": (
                    f"{field_name}[{i}] must be an object; "
                    f"got {type(entry).__name__}"
                ),
            }
        try:
            items.append(model_cls(**entry))
        except Exception as exc:
            return {
                "status": "error",
                "error": (
                    f"{field_name}[{i}] invalid: {type(exc).__name__}: {exc}"
                ),
            }
    return {"items": items}
