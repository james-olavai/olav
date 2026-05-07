"""Atomic CAB lab validation pipeline (Patch L).

Folds the 5+ step lab validation flow into a single composite call so
the lab agent makes ONE skill_script invocation instead of orchestrating
each step itself.  Solves ISSUE-CAB-AGENT-DRIVEN-LAB-VALIDATION-LOOPS:
small models stuck in the multi-step decision loop spent 12+ minutes
on tcf_load_for_lab alone before the runner timed out.

Phases (each phase failure short-circuits to ``destroy``):

    0. load      — tcf_load_for_lab(spec_path)
    1. topology  — generate_clab_topology(**r88_args)
    2. srl       — generate_srl_lab_config(**r89_args)
    3. save      — save_lab_config per node
    4. deploy    — deploy_and_push_lab
    5. verify    — exec each post_check, match against expected_pattern
    6. record    — tcf_record_lab_run with verdict + journal + step verdicts
    7. destroy   — destroy_lab (always attempted, even on phase failure)

Returns one envelope with all evidence.  Caller never has to thread
intermediate results between calls.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .tcf_io import tcf_load
from .tcf_lab import tcf_load_for_lab, tcf_record_lab_run


def _match_pattern(actual: str, expected: str) -> bool:
    """Per PostCheck schema: bare string → substring match (case-insensitive),
    ``re:<regex>`` prefix → regex match (case-insensitive, multiline).
    """
    if not isinstance(actual, str):
        return False
    if expected.startswith("re:"):
        try:
            return bool(re.search(expected[3:], actual, re.I | re.M))
        except re.error:
            return False
    return expected.lower() in actual.lower()


def _exec_check(
    lab_name: str,
    lab_node: str,
    command: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    """Run one post_check command on a CLAB node — same wrapping as
    the ``exec_on_node`` @tool (sr_cli auto-wrapping with base64 stdin).
    """
    import base64 as _b64

    from olav.platform.services.client import service_call

    container = f"clab-{lab_name}-{lab_node}"
    cmd = command.strip()
    if cmd.startswith("sr_cli") and not cmd.startswith("bash -c"):
        m = re.match(r"""^sr_cli\s+(?:-c\s+)?['"](.*)['"]\s*$""", cmd, re.DOTALL)
        srl_content = m.group(1) if m else re.sub(r"^sr_cli\s+(?:-c\s+)?", "", cmd)
        b64 = _b64.b64encode((srl_content.strip() + "\n").encode()).decode()
        cmd = f"bash -c 'echo {b64} | base64 -d | sr_cli 2>&1'"

    body = service_call(
        "containerlab",
        method="POST",
        path=f"/api/v1/labs/{lab_name}/exec",
        params={"nodeFilter": container},
        body={"command": cmd},
        confirmed=True,
        timeout=float(timeout),
    )

    if isinstance(body, dict):
        node_results = body.get(container, body.get(lab_node, []))
        if isinstance(node_results, list) and node_results:
            r = node_results[0]
            return {
                "stdout": r.get("stdout", ""),
                "stderr": r.get("stderr", ""),
                "return_code": r.get("return-code", 0),
            }
    return {"stdout": str(body), "stderr": "", "return_code": 0}


def validate_tcf_in_lab(
    spec_path: str | Path,
    *,
    destroy_on_finish: bool = True,
    skip_record: bool = False,
    exec_timeout: float = 30.0,
    deploy_wait_seconds: int = 40,
    post_commit_wait_seconds: int = 30,
    convergence_wait_seconds: int = 5,
) -> dict[str, Any]:
    """Run the full CAB lab validation pipeline atomically.

    Args:
        spec_path: Path to the TCF spec yaml.
        destroy_on_finish: Tear down the CLAB lab when done (default True).
            Set False for debugging — caller must destroy manually.
        skip_record: Don't write verdict + journal back to the TCF spec.
            Useful for dry-run / probe modes.
        exec_timeout: Per-post_check exec timeout.
        deploy_wait_seconds: First-deploy wait passed to ``deploy_and_push_lab``.
        post_commit_wait_seconds: Post-config-commit settle passed to
            ``deploy_and_push_lab``.
        convergence_wait_seconds: Extra grace before running post_checks
            (BGP/OSPF still converging after the post_commit_wait).

    Returns: envelope with
        ``status`` (ok / error), ``phase`` (which phase failed if error),
        ``verdict`` (PASS / FAIL — only present when at least the
        deploy + verify phases ran), ``lab_name``, ``spec_path``,
        ``post_check_results`` (list of per-check dicts with ``passed``,
        ``actual``, ...), ``tvt_results`` (matched by check_id ↔ test_id),
        ``journal`` (list of phase records), ``tcf_recorded``,
        ``lab_destroyed``, ``errors`` (cumulative non-fatal warnings).
    """
    spec_path = Path(spec_path)
    journal: list[dict[str, Any]] = []
    errors: list[str] = []
    lab_name = ""
    lab_destroyed = False
    deploy_was_attempted = False

    def _journal(step: str, phase: str, args: dict, summary: dict) -> None:
        journal.append({
            "step": step,
            "args": args,
            "result_summary": {**summary, "phase": phase},
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def _attempt_destroy() -> None:
        nonlocal lab_destroyed
        if not destroy_on_finish or not lab_name or not deploy_was_attempted:
            return
        try:
            from olav.core.lab.deploy_io import destroy_lab
            d = destroy_lab(lab_name, timeout=exec_timeout)
            lab_destroyed = bool(d.get("destroyed") or d.get("status") == "ok")
            _journal("destroy_lab", "destroy", {"lab_name": lab_name},
                     {"destroyed": lab_destroyed})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"destroy_lab failed: {type(exc).__name__}: {exc}")

    # ── Phase 0: load ─────────────────────────────────────────────────
    loaded = tcf_load_for_lab(spec_path)
    if loaded.get("status") != "ok":
        return {
            "status": "error",
            "phase": "load",
            "error": loaded.get("error", "tcf_load_for_lab failed"),
            "spec_path": str(spec_path),
            "journal": journal,
            "errors": errors,
            "tcf_recorded": False,
            "lab_destroyed": False,
        }
    r88_args = loaded["r88_args"]
    r89_args = loaded["r89_args"]
    lab_name = r88_args["lab_name"]
    post_check_specs = loaded["post_check"]
    tvt_specs = loaded["tvt"]
    _journal("tcf_load_for_lab", "load",
             {"spec_path": str(spec_path)},
             {"change_id": loaded["change_id"], "lab_name": lab_name})

    if r89_args is None:
        msg = loaded.get("r89_error", "intent not supported by R89")
        return {
            "status": "error", "phase": "load", "error": msg,
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": False,
        }

    # ── Phase 1: topology (R88-A) ─────────────────────────────────────
    try:
        from olav.core.lab.topology import generate_clab_topology
        yaml_content = generate_clab_topology(**r88_args)
    except Exception as exc:  # noqa: BLE001
        _attempt_destroy()
        return {
            "status": "error", "phase": "topology",
            "error": f"generate_clab_topology failed: {exc}",
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    if yaml_content.lstrip().startswith("# ERROR"):
        _attempt_destroy()
        return {
            "status": "error", "phase": "topology",
            "error": yaml_content.split("\n", 1)[0],
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    _journal("generate_clab_topology", "topology", r88_args,
             {"yaml_lines": len(yaml_content.splitlines())})

    # ── Phase 2: SRL render (R89) ─────────────────────────────────────
    try:
        from olav.core.lab.srl_render import generate_srl_lab_config
        srl_raw = generate_srl_lab_config(**r89_args)
        srl_result = json.loads(srl_raw)
    except Exception as exc:  # noqa: BLE001
        _attempt_destroy()
        return {
            "status": "error", "phase": "srl",
            "error": f"generate_srl_lab_config failed: {exc}",
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    if srl_result.get("status") != "ok":
        _attempt_destroy()
        return {
            "status": "error", "phase": "srl",
            "error": srl_result.get("error", "SRL render failed"),
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    configs = srl_result["configs"]  # dict[lab_node, list[str]]
    _journal("generate_srl_lab_config", "srl", r89_args,
             {"nodes": list(configs.keys()),
              "lines_per_node": {n: len(c) for n, c in configs.items()}})

    # ── Phase 3: save_lab_config per node ─────────────────────────────
    try:
        from olav.core.lab.deploy_io import save_lab_config
        for lab_node, cfg_lines in configs.items():
            lines = cfg_lines if isinstance(cfg_lines, list) else \
                str(cfg_lines).splitlines()
            r = save_lab_config(lab_name, lab_node, lines)
            if not r.get("saved"):
                raise RuntimeError(
                    f"save_lab_config({lab_node}) failed: {r.get('error')}"
                )
    except Exception as exc:  # noqa: BLE001
        _attempt_destroy()
        return {
            "status": "error", "phase": "save",
            "error": str(exc),
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    _journal("save_lab_config", "save", {"nodes": list(configs.keys())},
             {"saved": len(configs)})

    # ── Phase 4: deploy_and_push_lab ──────────────────────────────────
    deploy_was_attempted = True
    try:
        from olav.core.lab.deploy_and_push import deploy_and_push_lab
        deploy_result = deploy_and_push_lab(
            lab_name=lab_name,
            yaml_content=yaml_content,
            configs={},  # empty → auto-load from save_lab_config dropbox
            wait_seconds=deploy_wait_seconds,
            post_commit_wait_seconds=post_commit_wait_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        _attempt_destroy()
        return {
            "status": "error", "phase": "deploy",
            "error": f"deploy_and_push_lab raised: {exc}",
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }

    if isinstance(deploy_result, str):
        try:
            deploy_result = json.loads(deploy_result)
        except json.JSONDecodeError:
            deploy_result = {"raw": deploy_result}

    if not deploy_result.get("deployed") and not deploy_result.get("lab_reused"):
        _attempt_destroy()
        return {
            "status": "error", "phase": "deploy",
            "error": "deploy_and_push_lab did not deploy or reuse lab",
            "deploy_result": deploy_result,
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    _journal("deploy_and_push_lab", "deploy",
             {"lab_name": lab_name, "yaml_lines": len(yaml_content.splitlines())},
             {"deployed": deploy_result.get("deployed", False),
              "committed": deploy_result.get("committed", False),
              "lab_reused": deploy_result.get("lab_reused", False)})

    if convergence_wait_seconds > 0:
        time.sleep(convergence_wait_seconds)

    # ── Phase 5: verify each post_check ───────────────────────────────
    post_check_results: list[dict[str, Any]] = []
    for spec in post_check_specs:
        device = spec["device"]
        lab_node = device.lower()  # SRL render lowercases prod → lab
        try:
            r = _exec_check(
                lab_name, lab_node, spec["command"], timeout=exec_timeout
            )
            actual = r.get("stdout", "")
        except Exception as exc:  # noqa: BLE001
            actual = f"<exec error: {type(exc).__name__}: {exc}>"
            errors.append(f"exec {spec['check_id']} on {lab_node}: {exc}")
        passed = _match_pattern(actual, spec["expected_pattern"])
        post_check_results.append({
            "check_id": spec["check_id"],
            "device": device,
            "lab_node": lab_node,
            "command": spec["command"],
            "expected_pattern": spec["expected_pattern"],
            "actual": actual,
            "passed": passed,
        })
    verdict = "PASS" if (post_check_results and
                         all(r["passed"] for r in post_check_results)) else "FAIL"
    _journal("verify_post_check", "verify",
             {"checks": len(post_check_results)},
             {"verdict": verdict,
              "passed": sum(1 for r in post_check_results if r["passed"]),
              "failed": sum(1 for r in post_check_results if not r["passed"])})

    # ── Phase 5b: tvt mapping (best-effort by check_id ↔ test_id) ────
    check_by_id = {r["check_id"]: r for r in post_check_results}
    tvt_test_ids: list[str] = []
    tvt_actuals: list[str] = []
    tvt_statuses: list[str] = []
    tvt_results: list[dict[str, Any]] = []
    for trow in tvt_specs:
        tid = trow["test_id"]
        match = check_by_id.get(tid)
        if match is None:
            continue
        snippet = match["actual"][:200] if match["actual"] else ""
        status = "PASS" if match["passed"] else "FAIL"
        tvt_test_ids.append(tid)
        tvt_actuals.append(snippet)
        tvt_statuses.append(status)
        tvt_results.append({
            "test_id": tid,
            "expected": trow["expected"],
            "actual_lab": snippet,
            "status": status,
        })

    # step_verdicts is reserved for cross-verifying spec.implementation
    # vs lab.implementation_lab (per StepVerdict schema); the composite
    # doesn't push lab CLI back so leave empty — diff_spec_vs_lab is
    # the right tool to populate this later.
    step_verdicts: list[dict[str, Any]] = []

    # ── Phase 6: record back to TCF ──────────────────────────────────
    tcf_recorded = False
    if not skip_record:
        diagnosis = ""
        if verdict == "FAIL":
            failed = [r["check_id"] for r in post_check_results
                      if not r["passed"]]
            diagnosis = (
                f"Lab post_check FAIL on {len(failed)} of "
                f"{len(post_check_results)} checks: {failed}. "
                f"Inspect post_check_results.actual for details."
            )

        rec = tcf_record_lab_run(
            spec_path,
            verdict=verdict,
            lab_name=lab_name,
            tvt_test_ids=tvt_test_ids,
            tvt_actual_lab=tvt_actuals,
            tvt_status=tvt_statuses,
            journal=journal,
            diagnosis=diagnosis,
            step_verdicts=step_verdicts,
        )
        tcf_recorded = rec.get("status") == "ok"
        if not tcf_recorded:
            errors.append(
                f"tcf_record_lab_run: {rec.get('error', 'unknown')}"
            )

    # ── Phase 7: destroy ─────────────────────────────────────────────
    _attempt_destroy()

    return {
        "status": "ok",
        "phase": "complete",
        "verdict": verdict,
        "spec_path": str(spec_path),
        "lab_name": lab_name,
        "post_check_results": post_check_results,
        "tvt_results": tvt_results,
        "journal": journal,
        "tcf_recorded": tcf_recorded,
        "lab_destroyed": lab_destroyed,
        "errors": errors,
    }
