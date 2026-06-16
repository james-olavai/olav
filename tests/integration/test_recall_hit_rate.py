"""Recall hit-rate bench (P0c — dev_docs/58 R84 Phase 1.5b).

Independent of agent runs.  Tests memory retrieval quality directly:
given a representative set of natural-language queries with known
correct intents, what fraction lands the right ``usage_guide`` entry
in top-1 / top-3 / top-5 of the diversifier output?

This is the FAST test (~10s) that lets us iterate on LanceDB
optimisations (Tags FTS, score threshold, multi-vector) without
running expensive end-to-end LLM benches.

Run via either:
    pytest tests/integration/test_recall_hit_rate.py -v
or as a script for CSV output:
    python tests/integration/test_recall_hit_rate.py --json /tmp/hitrate.json

Targets (per dev_docs/57 § "Measurement"):
* top-1 hit rate ≥ 70% — guide directly recommended is correct
* top-3 hit rate ≥ 90% — agent will see correct guide in injected block
* top-5 hit rate ≥ 95% — failure modes mostly limited to truly
  ambiguous queries
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    import pytest
    _HAS_PYTEST = True
    pytest.importorskip("olav.core.memory")
    pytest.importorskip("olav.core.memory.middleware")
except ImportError:
    _HAS_PYTEST = False  # script-mode only


# ── Golden test set ────────────────────────────────────────────────
# (query, expected_intent_id_substring)  — substring match against
# the guide ``id`` (``guide_<agent>_<intent>``) so ordering/agent
# changes don't break the test.

GOLDEN: list[tuple[str, str]] = [
    # ── topology_visualization (8) ──
    ("Show the network topology as a Mermaid diagram", "topology_visualization"),
    ("Draw a topology graph for me", "topology_visualization"),
    ("Visualize the L2 topology", "topology_visualization"),
    ("Generate a Mermaid diagram of the network", "topology_visualization"),
    ("Render network topology as graph", "topology_visualization"),
    ("Show me the L2 topology layout", "topology_visualization"),
    ("Draw network diagram", "topology_visualization"),
    ("画一个网络拓扑图", "topology_visualization"),

    # ── simulation_what_if (8) ──
    ("Simulate what happens if R2 loses all links", "simulation_what_if"),
    ("What if R3 fails — analyse blast radius", "simulation_what_if"),
    ("Simulate decommissioning SW1", "simulation_what_if"),
    ("Run a what-if for R4 going down", "simulation_what_if"),
    ("Predict the impact of removing R2's WAN link", "simulation_what_if"),
    ("如果 R2 失联会影响什么", "simulation_what_if"),
    ("模拟 R3 故障", "simulation_what_if"),
    ("simulate failure of border router", "simulation_what_if"),

    # ── drift_detection (8) ──
    ("Compare the last two snapshots of R2", "drift_detection"),
    ("What changed between snapshots", "drift_detection"),
    ("Show drift between today and yesterday", "drift_detection"),
    ("Diff the network state between two captures", "drift_detection"),
    ("Has anything changed in the last hour", "drift_detection"),
    ("对比两个快照", "drift_detection"),
    ("漂移检测", "drift_detection"),
    ("compare snapshot A vs snapshot B", "drift_detection"),

    # ── save_artifact (6) ──
    ("Save the report to exports/", "save_artifact"),
    ("Export this analysis to a file", "save_artifact"),
    ("Write the result to disk", "save_artifact"),
    ("Save this as CSV", "save_artifact"),
    ("把结果保存到 exports/", "save_artifact"),
    ("export to .mmd file", "save_artifact"),
]

# Negative queries — generic ops queries that should NOT pull any
# usage_guide entry (none of the 4 intents apply).  Score threshold
# is the lever: with low cosine distance threshold, these get 0 guides.
# Without, the diversifier pads with unrelated guides and bloats the
# prompt — exactly the Q1 +33% regression we saw at N=5.
NEGATIVE_QUERIES: list[str] = [
    "How many devices do we have? Show their names, IPs, and roles.",
    "Are all BGP neighbors established?",
    "Which interfaces are down across all devices?",
    "What is R1's IP address?",
    "List OSPF neighbors for R3",
    "Show me the device inventory",
    "What's the platform of R2?",
    "How many BGP peers does R1 have?",
]


@dataclass
class QueryResult:
    query: str
    expected_intent: str
    top_5_intents: list[str]
    top_1_hit: bool
    top_3_hit: bool
    top_5_hit: bool
    top_distance: float | None  # cosine distance of top hit, if available


@dataclass
class NegativeResult:
    query: str
    guides_pulled: list[str]
    top_distance: float | None
    is_clean: bool  # True iff zero guides pulled — ideal


@dataclass
class HitRateReport:
    timestamp: str
    total: int
    top_1_hits: int
    top_3_hits: int
    top_5_hits: int
    top_1_rate: float
    top_3_rate: float
    top_5_rate: float
    by_intent: dict[str, dict[str, int | float]] = field(default_factory=dict)
    queries: list[QueryResult] = field(default_factory=list)
    negative_total: int = 0
    negative_clean: int = 0
    negative_clean_rate: float = 0.0
    negatives: list[NegativeResult] = field(default_factory=list)


def _intent_in_id(memory_id: str | None, expected: str) -> bool:
    return bool(memory_id) and expected in memory_id


def measure_hit_rate(top_k: int = 5) -> HitRateReport:
    """Run all golden queries; return aggregate hit-rate report."""
    from datetime import datetime
    from olav.core.memory import get_store
    from olav.core.memory.middleware import AutoRecallMiddleware
    from olav.core.embedder import embed_text

    store = get_store()
    if store is None:
        raise SystemExit("memory store unavailable — run ``/netops_init`` first")
    mw = AutoRecallMiddleware(store=store)
    fetch_k = max(top_k, mw._resolve_top_k())

    report = HitRateReport(
        timestamp=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        total=len(GOLDEN),
        top_1_hits=0,
        top_3_hits=0,
        top_5_hits=0,
        top_1_rate=0.0,
        top_3_rate=0.0,
        top_5_rate=0.0,
    )
    by_intent: dict[str, dict[str, int]] = {}

    for query, expected_intent in GOLDEN:
        vec = embed_text(query)
        candidates = mw._gather_candidates(query, vec, scope="global", top_k=fetch_k)
        # Apply same diversifier the live agent sees
        diversified = mw._diversify_by_category(candidates, fetch_k)

        # Filter to usage_guide only — that's the category we're testing
        guides = [m for m in diversified if m.get("category") == "usage_guide"]
        top_5_ids = [m.get("id", "") for m in guides[:5]]

        top_1 = bool(top_5_ids) and _intent_in_id(top_5_ids[0], expected_intent)
        top_3 = any(_intent_in_id(i, expected_intent) for i in top_5_ids[:3])
        top_5 = any(_intent_in_id(i, expected_intent) for i in top_5_ids[:5])

        top_distance = None
        if guides:
            for k in ("score", "_distance"):
                v = guides[0].get(k)
                if v is not None:
                    try:
                        top_distance = float(v)
                        break
                    except Exception:
                        pass

        report.queries.append(QueryResult(
            query=query,
            expected_intent=expected_intent,
            top_5_intents=top_5_ids,
            top_1_hit=top_1,
            top_3_hit=top_3,
            top_5_hit=top_5,
            top_distance=top_distance,
        ))
        report.top_1_hits += int(top_1)
        report.top_3_hits += int(top_3)
        report.top_5_hits += int(top_5)

        slot = by_intent.setdefault(expected_intent, {
            "total": 0, "top_1": 0, "top_3": 0, "top_5": 0,
        })
        slot["total"] += 1
        slot["top_1"] += int(top_1)
        slot["top_3"] += int(top_3)
        slot["top_5"] += int(top_5)

    n = report.total
    report.top_1_rate = round(report.top_1_hits / n, 3)
    report.top_3_rate = round(report.top_3_hits / n, 3)
    report.top_5_rate = round(report.top_5_hits / n, 3)
    for intent, s in by_intent.items():
        s["top_1_rate"] = round(s["top_1"] / s["total"], 3)
        s["top_3_rate"] = round(s["top_3"] / s["total"], 3)
        s["top_5_rate"] = round(s["top_5"] / s["total"], 3)
    report.by_intent = by_intent

    # Negative queries — should pull 0 guides (or guides with very high
    # distance / very low relevance).  This is what score threshold
    # is meant to clean up.
    report.negative_total = len(NEGATIVE_QUERIES)
    for nq in NEGATIVE_QUERIES:
        nv = embed_text(nq)
        nc = mw._gather_candidates(nq, nv, scope="global", top_k=fetch_k)
        nd = mw._diversify_by_category(nc, fetch_k)
        ng = [m for m in nd if m.get("category") == "usage_guide"]
        ng_ids = [m.get("id", "") for m in ng]
        td = None
        if ng:
            for k in ("score", "_distance"):
                v = ng[0].get(k)
                if v is not None:
                    try:
                        td = float(v)
                        break
                    except Exception:
                        pass
        clean = len(ng) == 0
        report.negatives.append(NegativeResult(
            query=nq,
            guides_pulled=ng_ids,
            top_distance=td,
            is_clean=clean,
        ))
        report.negative_clean += int(clean)
    report.negative_clean_rate = round(
        report.negative_clean / report.negative_total, 3,
    ) if report.negative_total else 0.0

    return report


# ── Pytest path ────────────────────────────────────────────────────


def test_top_3_hit_rate_meets_threshold():
    """Gate: ≥ 90% top-3 hit rate.  Adjust threshold as recall improves."""
    report = measure_hit_rate()
    print(
        f"\nrecall hit-rate: top-1={report.top_1_rate:.0%} "
        f"top-3={report.top_3_rate:.0%} top-5={report.top_5_rate:.0%}",
        flush=True,
    )
    assert report.top_3_rate >= 0.90, (
        f"top-3 hit rate {report.top_3_rate:.0%} below 90% threshold; "
        f"misses: {[(q.query, q.expected_intent) for q in report.queries if not q.top_3_hit]}"
    )


# ── Script path ────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="Optional JSON output path")
    ap.add_argument(
        "--demo-dir",
        default=os.environ.get("OLAV_DEMO_DIR", str(Path.home() / "olav-demo6")),
    )
    args = ap.parse_args()

    os.chdir(args.demo_dir)  # so default memory paths resolve to demo6
    report = measure_hit_rate()

    print(f"\n=== recall hit-rate ({report.total} queries) ===")
    print(f"  top-1: {report.top_1_hits}/{report.total} ({report.top_1_rate:.1%})")
    print(f"  top-3: {report.top_3_hits}/{report.total} ({report.top_3_rate:.1%})")
    print(f"  top-5: {report.top_5_hits}/{report.total} ({report.top_5_rate:.1%})")

    print("\nby intent:")
    for intent, s in report.by_intent.items():
        print(f"  {intent:32}  "
              f"top-1: {s['top_1']:>2}/{s['total']} ({s['top_1_rate']:.0%})  "
              f"top-3: {s['top_3']:>2}/{s['total']} ({s['top_3_rate']:.0%})")

    misses = [q for q in report.queries if not q.top_3_hit]
    if misses:
        print(f"\ntop-3 misses ({len(misses)}):")
        for m in misses:
            print(f"  [{m.expected_intent}] {m.query!r}")
            print(f"    saw: {m.top_5_intents}")

    print(f"\n=== noise (negative queries — {report.negative_total} queries) ===")
    print(f"  clean (0 guides pulled): {report.negative_clean}/"
          f"{report.negative_total} ({report.negative_clean_rate:.1%})")
    if report.negative_clean < report.negative_total:
        print("  noisy queries (pulled unrelated guides):")
        for n in report.negatives:
            if not n.is_clean:
                print(f"    {n.query!r}")
                print(f"      pulled: {n.guides_pulled}  top_dist={n.top_distance}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(asdict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n→ wrote {args.json}")


if __name__ == "__main__":
    main()
