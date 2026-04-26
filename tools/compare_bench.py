#!/usr/bin/env python3
"""Compare two bench JSON outputs side-by-side.

Usage:
    python tools/compare_bench.py /tmp/bench_baseline_*.json \
                                  /tmp/bench_with_guides_*.json

Emits a Markdown table to stdout suitable for pasting into PRs / docs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fmt_delta(before: float, after: float, lower_is_better: bool = True) -> str:
    """Format ``+/-N (M%)`` with arrow indicating direction."""
    delta = after - before
    pct = (delta / before * 100) if before else 0.0
    if abs(delta) < 0.05:
        return f"{after:>5.1f} (=)"
    arrow = "↓" if (lower_is_better and delta < 0) or (not lower_is_better and delta > 0) else "↑"
    sign = "+" if delta > 0 else ""
    return f"{after:>5.1f} {arrow} {sign}{delta:.1f} ({sign}{pct:.0f}%)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline", help="Baseline JSON (no guides)")
    ap.add_argument("with_guides", help="With-guides JSON")
    args = ap.parse_args()

    base = load(args.baseline)
    after = load(args.with_guides)

    # Index summary by query_id
    base_q = {s["query_id"]: s for s in base["summary"]}
    after_q = {s["query_id"]: s for s in after["summary"]}

    common = sorted(set(base_q) & set(after_q))
    if not common:
        print("ERROR: no overlapping query_ids", file=sys.stderr)
        sys.exit(1)

    print(f"# Phase 1 bench comparison")
    print()
    print(f"- baseline:    `{Path(args.baseline).name}` "
          f"({base['runs_per_query']} runs/query)")
    print(f"- with_guides: `{Path(args.with_guides).name}` "
          f"({after['runs_per_query']} runs/query)")
    print()
    print("## Tool calls (lower is better)")
    print()
    print("| query | agent | baseline mean | with_guides mean | delta |")
    print("|-------|-------|--------------:|-----------------:|------:|")
    for qid in common:
        b, a = base_q[qid], after_q[qid]
        delta = fmt_delta(b["tool_calls_mean"], a["tool_calls_mean"], True)
        print(f"| {qid} | {a['agent']} | "
              f"{b['tool_calls_mean']:.1f} (±{b['tool_calls_std']:.1f}) | "
              f"{a['tool_calls_mean']:.1f} (±{a['tool_calls_std']:.1f}) | "
              f"{delta} |")

    print()
    print("## Wall clock (lower is better)")
    print()
    print("| query | baseline mean | with_guides mean | delta |")
    print("|-------|--------------:|-----------------:|------:|")
    for qid in common:
        b, a = base_q[qid], after_q[qid]
        delta = fmt_delta(b["elapsed_mean"], a["elapsed_mean"], True)
        print(f"| {qid} | {b['elapsed_mean']:.0f}s | "
              f"{a['elapsed_mean']:.0f}s | {delta} |")

    print()
    print("## Correctness rate (higher is better)")
    print()
    print("| query | baseline | with_guides | delta |")
    print("|-------|---------:|------------:|------:|")
    for qid in common:
        b, a = base_q[qid], after_q[qid]
        delta_pct = (a["correctness_rate"] - b["correctness_rate"]) * 100
        sign = "+" if delta_pct > 0 else ""
        arrow = "↑" if delta_pct > 0 else ("↓" if delta_pct < 0 else "=")
        print(f"| {qid} | {b['correctness_rate']:.0%} | "
              f"{a['correctness_rate']:.0%} | "
              f"{arrow} {sign}{delta_pct:.0f}pp |")

    print()
    print("## SaveAssertion fired rate (lower is better — fewer hallucinations to recover)")
    print()
    print("| query | baseline | with_guides | delta |")
    print("|-------|---------:|------------:|------:|")
    for qid in common:
        b, a = base_q[qid], after_q[qid]
        delta_pct = (a["save_assertion_rate"] - b["save_assertion_rate"]) * 100
        sign = "+" if delta_pct > 0 else ""
        arrow = "↓" if delta_pct < 0 else ("↑" if delta_pct > 0 else "=")
        print(f"| {qid} | {b['save_assertion_rate']:.0%} | "
              f"{a['save_assertion_rate']:.0%} | "
              f"{arrow} {sign}{delta_pct:.0f}pp |")

    # Summary verdict
    print()
    print("## Summary")
    print()
    base_total_calls = sum(s["tool_calls_mean"] for s in base["summary"])
    after_total_calls = sum(s["tool_calls_mean"] for s in after["summary"])
    base_correct = sum(s["correctness_rate"] for s in base["summary"]) / len(base["summary"])
    after_correct = sum(s["correctness_rate"] for s in after["summary"]) / len(after["summary"])
    print(f"- Total mean tool calls across queries: "
          f"{base_total_calls:.1f} → {after_total_calls:.1f} "
          f"({(after_total_calls - base_total_calls):+.1f}, "
          f"{((after_total_calls - base_total_calls) / base_total_calls * 100):+.0f}%)")
    print(f"- Mean correctness rate: "
          f"{base_correct:.0%} → {after_correct:.0%} "
          f"({(after_correct - base_correct) * 100:+.0f}pp)")


if __name__ == "__main__":
    main()
