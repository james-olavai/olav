"""tcf_record_lab_run — R90 Phase 3 lab→TCF write-back.

Single-call tool that updates a TCF's ``lab.*`` section + TVT
``actual_lab`` / ``status`` columns atomically.

Replaces F3's ``append_validation_footer``:
  * F3 appended a markdown footer to the spec — opaque, free-text
  * R90 lab section is structured — verdict + journal + per-test
    actuals, queryable, diff-able

Schema flexibility note: TVT updates use **3 parallel arrays**
(``tvt_test_ids`` / ``tvt_actual_lab`` / ``tvt_status``) instead of
a list of dicts. Small-model tool-arg construction is much more
reliable on flat arrays — same pattern that fixed R89's first
iteration.

Journal entries are passed as a JSON string (``journal_json``).
Agents construct JSON freely in text but struggle to construct
nested ``list[dict]`` tool-arg objects.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT and not (_PROJECT_ROOT / "pyproject.toml").exists():
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


from langchain_core.tools import tool


@tool
def tcf_record_lab_run(
    spec_path: str,
    verdict: str,
    lab_name: str,
    snapshot_id: str = "",
    diagnosis: str = "",
    recommendation: list[str] | None = None,
    tvt_test_ids: list[str] | None = None,
    tvt_actual_lab: list[str] | None = None,
    tvt_status: list[str] | None = None,
    journal_json: str = "[]",
) -> str:
    """Atomically record the lab run results into the TCF spec file.

    Call this AT THE END of the lab workflow, AFTER format_and_export
    writes the standalone CAB report and BEFORE destroy_lab.
    Replaces the F3 ``append_validation_footer`` markdown footer
    with a structured update to the TCF.

    Args:
        spec_path: Path to the TCF YAML file the lab validated.
            Must exist on disk and be a valid TCF (Pydantic
            re-validates after the update).
        verdict: ``"PASS"`` / ``"FAIL"`` / ``"BLOCKED"``. Free string
            but stick to convention.
        lab_name: The CLAB lab name used (e.g. ``"cab_001_lab"``).
        snapshot_id: netops snapshot ref the lab built from
            (e.g. ``"2026-03-30_2210"``). Empty string if not
            applicable.
        diagnosis: Free-form text. For FAIL: the lab's diagnosis
            of why. For PASS: usually empty.
        recommendation: List of action items for the next sim
            revision (FAIL) or deployment notes (PASS). Each entry
            is a single-line string.
        tvt_test_ids: Test IDs to update, in same order as the next
            two arrays. Subset of TCF.tvt[*].test_id; unknown IDs
            error.
        tvt_actual_lab: Lab-observed value for each test_id, same
            length as tvt_test_ids.
        tvt_status: Status string per test_id (``"PASS"`` /
            ``"FAIL"`` / ``"BLOCKED"`` / ``"PENDING"``), same
            length as tvt_test_ids.
        journal_json: JSON string of a list of journal entries.
            Each entry is a dict with at least ``step`` (str) and
            optional ``args`` / ``result_summary`` / ``timestamp``.
            Tool parses + validates. Empty default ``"[]"``.

    Returns:
        JSON envelope:
          status: "ok" / "error"
          spec_path: <where written>
          updated_tvt: <count of tvt rows updated>
          journal_entries: <count appended>

        On error (file missing, FK mismatch on tvt IDs, malformed
        journal JSON), returns status="error" with details. Original
        file is NOT modified on error (atomic write via temp file).

    Example:
        >>> tcf_record_lab_run(
        ...     spec_path="exports/cab/cab_001/spec.tcf.yaml",
        ...     verdict="PASS",
        ...     lab_name="cab_001_lab",
        ...     snapshot_id="2026-03-30_2210",
        ...     tvt_test_ids=["T1", "T2"],
        ...     tvt_actual_lab=["Established", "1 route each"],
        ...     tvt_status=["PASS", "PASS"],
        ...     journal_json='[{"step":"generate_clab_topology",'
        ...                  '"args":{"nodes":["R1","R4"]}, '
        ...                  '"result_summary":{"links":1}}]',
        ...     diagnosis="",
        ...     recommendation=["Deploy as-is; lab confirms convergence"],
        ... )
    """
    try:
        from olav.core.cab import tcf_emit, tcf_load
        from olav.core.cab.tcf_schema import JournalEntry
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"olav.core.cab unavailable: {type(exc).__name__}: {exc}",
        })

    # 1. Load existing TCF (validates schema)
    try:
        tcf = tcf_load(spec_path)
    except FileNotFoundError:
        return json.dumps({
            "status": "error",
            "error": f"TCF file not found: {spec_path}",
        })
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"TCF load failed: {type(exc).__name__}: {exc}",
        })

    # 2. Validate TVT update arrays
    test_ids = tvt_test_ids or []
    actuals = tvt_actual_lab or []
    statuses = tvt_status or []
    if not (len(test_ids) == len(actuals) == len(statuses)):
        return json.dumps({
            "status": "error",
            "error": (
                f"tvt_test_ids / tvt_actual_lab / tvt_status must be "
                f"same length: got {len(test_ids)} / {len(actuals)} "
                f"/ {len(statuses)}"
            ),
        })

    known_ids = {row.test_id for row in tcf.tvt}
    unknown = [tid for tid in test_ids if tid not in known_ids]
    if unknown:
        return json.dumps({
            "status": "error",
            "error": (
                f"unknown test_ids in tvt update: {unknown}. "
                f"Known: {sorted(known_ids)}"
            ),
        })

    # 3. Parse journal JSON
    try:
        journal_raw = json.loads(journal_json) if journal_json else []
    except json.JSONDecodeError as exc:
        return json.dumps({
            "status": "error",
            "error": f"journal_json is not valid JSON: {exc}",
        })
    if not isinstance(journal_raw, list):
        return json.dumps({
            "status": "error",
            "error": (
                f"journal_json must be a JSON array; got "
                f"{type(journal_raw).__name__}"
            ),
        })

    journal_entries: list[JournalEntry] = []
    for i, raw in enumerate(journal_raw):
        if not isinstance(raw, dict):
            return json.dumps({
                "status": "error",
                "error": f"journal_json[{i}] must be a JSON object; got {type(raw).__name__}",
            })
        try:
            journal_entries.append(JournalEntry(**raw))
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": f"journal_json[{i}] invalid: {type(exc).__name__}: {exc}",
            })

    # 4. Apply updates to the loaded TCF
    update_map = dict(zip(test_ids, zip(actuals, statuses, strict=True), strict=True))
    updated_count = 0
    for row in tcf.tvt:
        if row.test_id in update_map:
            actual, status = update_map[row.test_id]
            row.actual_lab = actual
            row.status = status
            updated_count += 1

    tcf.lab.verdict = verdict
    tcf.lab.lab_name = lab_name or None
    tcf.lab.snapshot_id = snapshot_id or None
    tcf.lab.ran_at = datetime.now(UTC)
    tcf.lab.journal = journal_entries
    tcf.lab.diagnosis = diagnosis
    tcf.lab.recommendation = list(recommendation or [])

    # 5. Atomic write back (Pydantic re-validates via tcf_emit's
    # model_dump path; the FK validators run again)
    try:
        out = tcf_emit(tcf, spec_path)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"TCF emit failed: {type(exc).__name__}: {exc}",
        })

    return json.dumps({
        "status": "ok",
        "spec_path": str(out),
        "verdict": verdict,
        "updated_tvt": updated_count,
        "journal_entries": len(journal_entries),
        "lab_name": lab_name,
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    args = json.loads(parsed.args_json)
    print(tcf_record_lab_run.invoke(args))
