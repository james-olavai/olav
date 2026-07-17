"""Governance: never filter ``netops.raw_output_store`` by ``snapshot_id``.

``raw_output_store`` is a SINGLE-COPY, current-state table — its conflict
key is ``(device_name, command)`` with NO ``snapshot_id`` (see
``olav_netops.core.tables.RawOutputStoreTable`` and
``olav.core.ingest_manager.IngestManager.bulk_load`` Step 1). Each ingest
overwrites in place; the ``snapshot_id`` column is a *last-writer label*,
not a partition key.

Consequence: a query like ``... FROM netops.raw_output_store WHERE
snapshot_id = <latest>`` silently returns 0 rows whenever the "latest"
import didn't carry that (device, command) — e.g. a state-only bundle with
no ``show running-config`` leaves the config text stamped under an OLDER
label. This is the exact trap that produced the Batfish
"No valid configurations" saga: the config was in the store all along,
under a non-latest snapshot label.

The correct patterns (already used by the shipped guides):
  * config text  → ``WHERE command = 'show running-config'`` (+ device_name),
    NO snapshot_id filter;
  * config-layer / Batfish snapshot resolution →
    ``batfish_q._latest_snapshot_with_configs()``.

This test is a zero-LLM gate that scans every netops workspace SKILL.md,
``*.guide.yaml`` and reference doc for the forbidden predicate, and asserts
the table definition still documents the single-copy semantics.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: All netops workspace trees that may ship prompt/guide text to a model.
#: Drift between them is guarded elsewhere; here we scan every copy that
#: exists so a violation cannot hide in whichever tree gets deployed.
_WORKSPACE_ROOTS = [
    REPO / "olav-netops" / ".olav" / "workspace" / "netops",
    REPO / ".olav" / "workspace" / "netops",
    REPO / "olav-netops" / "src" / "olav_netops" / "data" / "skillpack"
    / ".olav" / "workspace" / "netops",
]

_SCAN_SUFFIXES = {".md", ".yaml", ".yml"}

# A FROM/JOIN onto raw_output_store (optionally schema-qualified).
_FROM_RAW = re.compile(r"\b(?:from|join)\s+(?:netops\.)?raw_output_store\b", re.I)
# End of a SQL statement / code region we shouldn't scan past.
_STMT_END = re.compile(r";|```|^\s*$")
# A snapshot_id predicate (comparison, not just a mention of the column).
_SNAPSHOT_PREDICATE = re.compile(r"\bsnapshot_id\b\s*(=|!=|<>|<|>|\bin\b|\blike\b)", re.I)


def _find_violations(text: str) -> list[tuple[int, str]]:
    """Return (line_no, line) for every raw_output_store statement that
    carries a snapshot_id predicate before the statement terminates."""
    lines = text.splitlines()
    violations: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if not _FROM_RAW.search(line):
            continue
        # Walk forward through the same statement (until ; / fence / blank).
        # Check the predicate BEFORE the terminator so a one-line
        # ``... WHERE snapshot_id = x;`` (predicate on the terminating line)
        # is still caught.
        for j in range(i, min(i + 12, len(lines))):
            frag = lines[j]
            if _SNAPSHOT_PREDICATE.search(frag):
                violations.append((j + 1, frag.strip()))
                break
            if j > i and _STMT_END.search(frag):
                break
    return violations


def _iter_scan_files():
    for root in _WORKSPACE_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() in _SCAN_SUFFIXES and path.is_file():
                yield path


def test_no_guide_filters_raw_output_store_by_snapshot_id():
    """No prompt/guide SQL may filter raw_output_store by snapshot_id."""
    offenders: list[str] = []
    scanned = 0
    for path in _iter_scan_files():
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        # Cheap pre-filter — both tokens must appear at all.
        if "raw_output_store" not in text or "snapshot_id" not in text:
            continue
        for line_no, frag in _find_violations(text):
            rel = path.relative_to(REPO)
            offenders.append(f"{rel}:{line_no}: {frag}")

    assert scanned > 0, "no netops workspace files scanned — path drift?"
    assert not offenders, (
        "raw_output_store is a single-copy current-state table; filtering it "
        "by snapshot_id silently drops config rows (Batfish 'No valid "
        "configurations' trap). Use WHERE command='show running-config' "
        "(no snapshot_id), or batfish_q._latest_snapshot_with_configs().\n"
        + "\n".join(offenders)
    )


def test_raw_output_store_table_documents_single_copy_semantics():
    """The table definition must keep the single-copy contract explicit so
    the governance rule above has a source of truth to point at."""
    from olav_netops.core.tables import RawOutputStoreTable

    # conflict key must NOT include snapshot_id — that is the whole reason
    # snapshot_id is a last-writer label rather than a partition key.
    assert "snapshot_id" not in RawOutputStoreTable.conflict_key, (
        "raw_output_store.conflict_key must stay (device_name, command) with "
        "NO snapshot_id — adding it would silently change the single-copy "
        "semantics this governance rule depends on."
    )
    doc = (RawOutputStoreTable.__doc__ or "").lower()
    assert "snapshot_id" in doc and "last-writer" in doc, (
        "RawOutputStoreTable docstring must explain that snapshot_id is a "
        "last-writer label, not a partition key (see governance rationale)."
    )
