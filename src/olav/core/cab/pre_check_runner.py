"""Pre-check evaluator for prod-side CAB gating (ARCH-34 prod side).

The lab side of pre_check execution lives in ``tcf_validate.py`` and
is informational — the lab is fresh-deployed so most pre_check
assertions don't reflect prod state. The PROD side is the real gate:
before pushing implementation to the production fleet, every pre_check
must pass; any failure aborts the deploy and surfaces for HITL.

This module provides the **gate evaluator** in pure Python:
    * Takes a ``CabTcf`` (loaded spec) + an executor callable
    * Runs each ``pre_check`` row through the executor
    * Applies the ``must_match`` polarity to decide pass/fail
    * Returns a structured envelope; caller decides whether to push
      ``implementation`` or surface the failure

The executor is a dependency-inverted hook so this module stays free
of Nornir / Scrapli / NAPALM imports (those live in olav-netops, and
core can't depend on them per ADR-0002 repo boundary). A real prod
runner — typically in ``olav-netops/.olav/workspace/netops/scripts/``
or a future ``deploy`` sub-agent — supplies a Nornir-based executor
and calls ``run_prod_pre_check`` here.

Public API:
    * ``run_prod_pre_check(tcf, executor)`` — main entry point
    * ``ProdExecutor`` — protocol describing the executor signature
    * verdict semantics:
        ``GATE_PASS``   — all pre_check rows passed; safe to push
        ``GATE_FAIL``   — at least one pre_check failed; ABORT push
        ``GATE_ERROR``  — at least one pre_check raised at exec time
                          (transport / connection / timeout); abort
        ``NO_CHECKS``   — spec has no pre_check rows; caller decides
                          whether absence is acceptable
"""
from __future__ import annotations

import re
from typing import Any, Callable, Literal, Protocol

from .tcf_schema import CabTcf, PreCheck


GateVerdict = Literal["GATE_PASS", "GATE_FAIL", "GATE_ERROR", "NO_CHECKS"]


class ProdExecutor(Protocol):
    """Signature a prod-side executor must satisfy.

    The runner calls ``executor(device, command)`` for each pre_check
    row. Return either:
        * ``{"stdout": str, "return_code": int}`` on success
        * ``{"error": str}`` on transport / timeout / auth failure
          (no stdout key — runner treats absence as GATE_ERROR)

    Implementation is up to the caller — Nornir + Scrapli is the
    common path for OLAV; SSH-direct, NAPALM, or REST API are also
    valid.
    """

    def __call__(self, device: str, command: str) -> dict[str, Any]:
        ...


def _match_pattern(actual: str, expected: str) -> bool:
    """Pattern matcher mirrors tcf_validate._match_pattern semantics:
    bare string → case-insensitive substring; ``re:<regex>`` prefix
    → regex match. This duplication keeps the prod runner free of
    importing tcf_validate (which pulls in lab + service_call deps).
    """
    if not isinstance(actual, str):
        return False
    if expected.startswith("re:"):
        try:
            return bool(re.search(expected[3:], actual, re.I | re.M))
        except re.error:
            return False
    return expected.lower() in actual.lower()


def _evaluate_one(
    check: PreCheck,
    executor: ProdExecutor,
) -> dict[str, Any]:
    """Run one pre_check on prod and return a result envelope row."""
    base = {
        "device": check.device,
        "check_id": check.check_id,
        "description": check.description,
        "command": check.command,
        "expected_pattern": check.expected_pattern,
        "must_match": check.must_match,
    }
    try:
        out = executor(check.device, check.command)
    except Exception as exc:  # noqa: BLE001 — surface as GATE_ERROR row
        return {
            **base,
            "exec_status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "actual": "",
            "passed": False,
        }
    if "error" in out:
        return {
            **base,
            "exec_status": "error",
            "error": str(out["error"]),
            "actual": out.get("stdout", ""),
            "passed": False,
        }
    actual = out.get("stdout", "")
    match = _match_pattern(actual, check.expected_pattern)
    passed = match if check.must_match else (not match)
    return {
        **base,
        "exec_status": "ok",
        "actual": actual,
        "passed": passed,
    }


def run_prod_pre_check(
    tcf: CabTcf,
    executor: ProdExecutor,
) -> dict[str, Any]:
    """Execute every ``pre_check`` row on prod and gate on results.

    Args:
        tcf: Loaded TCF spec (use ``tcf_load(spec_path)``).
        executor: Callable that runs ``(device, command)`` against
            the production device. See :class:`ProdExecutor`.

    Returns:
        Envelope with::

            {
                "verdict": "GATE_PASS" | "GATE_FAIL" | "GATE_ERROR" | "NO_CHECKS",
                "results": [{check_id, device, command, expected_pattern,
                             must_match, exec_status, actual, passed,
                             [error]}, ...],
                "passed_count": int,
                "failed_count": int,
                "error_count": int,
                "diagnosis": str,  # one-line summary for HITL
            }

        ``GATE_PASS`` is the ONLY verdict that should let the caller
        proceed to push implementation. Any other verdict means HITL
        must intervene.

    The runner ALWAYS executes every pre_check (no fail-fast) so the
    diagnosis surfaces every blocker at once instead of forcing the
    operator to fix-rerun-discover-next-blocker.
    """
    if not tcf.pre_check:
        return {
            "verdict": "NO_CHECKS",
            "results": [],
            "passed_count": 0,
            "failed_count": 0,
            "error_count": 0,
            "diagnosis": (
                "Spec has no pre_check rows. Either intent doesn't "
                "support pre_check yet, or the spec was authored "
                "before ARCH-34. Caller decides whether to proceed."
            ),
        }

    results: list[dict[str, Any]] = []
    for check in tcf.pre_check:
        results.append(_evaluate_one(check, executor))

    passed = sum(1 for r in results if r["passed"])
    failed = sum(
        1 for r in results
        if not r["passed"] and r["exec_status"] == "ok"
    )
    errored = sum(1 for r in results if r["exec_status"] == "error")

    if errored:
        verdict: GateVerdict = "GATE_ERROR"
        offending = [r["check_id"] for r in results
                     if r["exec_status"] == "error"]
        diagnosis = (
            f"{errored} of {len(results)} pre_check rows could not "
            f"execute (transport / timeout / auth): {offending}. "
            "Resolve connectivity before retrying — pre_check that "
            "errors out cannot prove preconditions hold."
        )
    elif failed:
        verdict = "GATE_FAIL"
        offending = [r["check_id"] for r in results if not r["passed"]]
        diagnosis = (
            f"{failed} of {len(results)} pre_check assertions failed: "
            f"{offending}. ABORT implementation push — preconditions "
            "for safe deploy do NOT hold. Inspect results[].actual to "
            "see what each check observed; common causes: lab_subnet "
            "already routed, picked interface in use, AS conflict, "
            "stale topology DB."
        )
    else:
        verdict = "GATE_PASS"
        diagnosis = (
            f"All {passed} pre_check assertions passed. Safe to "
            "push implementation."
        )

    return {
        "verdict": verdict,
        "results": results,
        "passed_count": passed,
        "failed_count": failed,
        "error_count": errored,
        "diagnosis": diagnosis,
    }


def make_dry_run_executor(
    fixtures: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> ProdExecutor:
    """Build a no-op executor that returns canned responses keyed by
    ``(device, command)``.

    Useful for unit tests + dry-run mode where the operator wants to
    see how the gate would evaluate without actually touching prod.

    Args:
        fixtures: ``{(device, command): {stdout, return_code}}``.
            Keys not in the dict default to a stdout that contains
            neither the expected_pattern nor any obvious negative
            marker — i.e., ambiguous responses surface as GATE_ERROR
            with a hint, NOT silent passes.

    Returns:
        Callable matching :class:`ProdExecutor`.
    """
    fixtures = dict(fixtures or {})

    def _exec(device: str, command: str) -> dict[str, Any]:
        key = (device, command)
        if key in fixtures:
            return fixtures[key]
        return {
            "error": (
                f"dry_run executor has no fixture for "
                f"({device!r}, {command!r}); supply one or use a real "
                "Nornir executor"
            ),
        }

    return _exec


__all__ = [
    "GateVerdict",
    "ProdExecutor",
    "make_dry_run_executor",
    "run_prod_pre_check",
]
