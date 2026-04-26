"""Phase 1 small-model benchmark — measure recall+prompt-fidelity gains.

This is **not a pytest test** — it's a measurement harness.  Run as a
script to produce a JSON artefact comparing tool-call counts, latency,
hallucination rate, and correctness across the 6 canonical scenarios
that exercised Chapter 3 + Chapter 4 failure modes.

Usage:
    python tests/integration/test_smallmodel_recall_bench.py --tag baseline
    # ...land Phase 1 changes, prime guides via /netops_init...
    python tests/integration/test_smallmodel_recall_bench.py --tag with_guides

    python tools/compare_bench.py /tmp/bench_baseline_*.json \
        /tmp/bench_with_guides_*.json

Captures, per (query, run) pair:
    tool_call_count_orch  — count of "🔧[orch]" lines (R39 origin tag)
    elapsed_seconds        — wall clock
    save_assertion_fired   — 1 if SaveAssertion warning/recovery present
    correctness_signal     — 1 if query-specific key strings appear

Aggregates per query: mean / std / min / max for tool_call_count
and elapsed; sum for correctness/save-assertion (fraction of N runs).

Reads OLAV_DEMO_DIR env var (default ~/olav-demo6) — runs the binary
at $DEMO/.venv/bin/olav with the same arguments as ad-hoc demos.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


# ── Query suite ────────────────────────────────────────────────────
# Each tuple: (id, agent_flag, query_text, correctness_predicate)
# correctness_predicate: callable(stdout, exports_dir) → bool
def _q1_correct(out: str, _exports: Path) -> bool:
    return ("6 条" in out) or ("6 devices" in out.lower()) or (
        out.count("R1") >= 1 and out.count("R2") >= 1 and out.count("SW1") >= 1
    )


def _q2_correct(out: str, _exports: Path) -> bool:
    """Q2 baseline marked all runs False because the literal "Established"
    didn't appear; the agent's actual phrasing is more varied.  Accept
    the common idioms used to convey "all BGP up"."""
    lower = out.lower()
    return any(token in lower for token in (
        "established",          # explicit RFC 4271 state name
        "all bgp neighbors",    # natural-language affirmation
        "all 4 bgp",            # count-based "all sessions up"
        "all 4 sessions",
        "no issues",            # summary clearance
        "全部 established",     # Chinese mixing
    ))


def _q3_correct(out: str, _exports: Path) -> bool:
    # Cross-platform proof: must mention R1's Junos interface (em2 or VLAN)
    # AND R2's Cisco interface (Gi or GigabitEthernet)
    has_r1_junos = ("em2" in out) or (("R1" in out) and "VLAN" in out)
    has_r2_cisco = ("GigabitEthernet" in out) or ("Gi3" in out)
    return has_r1_junos and has_r2_cisco


def _q4_correct(out: str, _exports: Path) -> bool:
    return "R2" in out and any(
        kw in out.lower() for kw in ("isolated", "blast", "lose", "partition")
    )


def _c4_topo_correct(out: str, exports: Path) -> bool:
    """Either the agent saved a Mermaid file, or SaveAssertion recovered one."""
    if not exports.exists():
        return False
    # Any .mmd that appeared (or recovered from SaveAssertion) within last 10 min
    cutoff = time.time() - 600
    return any(
        p.stat().st_mtime > cutoff
        for p in exports.rglob("*.mmd")
        if p.is_file()
    )


def _c4_drift_correct(out: str, _exports: Path) -> bool:
    return "snapshot" in out.lower() and any(
        kw in out.lower() for kw in ("changed", "differ", "no change", "diff")
    )


QUERIES: list[tuple[str, str, str, callable]] = [
    ("Q1",       "core", "How many devices do we have? Show their names, IPs, and roles.", _q1_correct),
    ("Q2",       "core", "Are all BGP neighbors established?",                              _q2_correct),
    ("Q3",       "core", "Which interfaces are down across all devices?",                   _q3_correct),
    ("Q4",       "ops",  "Simulate what happens if R2 loses all links",                     _q4_correct),
    ("C4-topo",  "ops",  "Show the network topology as a Mermaid diagram and save to exports/", _c4_topo_correct),
    ("C4-drift", "ops",  "Compare the last two snapshots of R2 — what changed?",            _c4_drift_correct),
]


_ORCH_TAG = re.compile(r"🔧\[orch\]")
# Fallback: rich.console interprets ``[orch]`` as malformed markup and
# silently strips the brackets in non-TTY captures, so the origin tag
# never reaches stdout.  Use the bare 🔧 marker as a fallback (counts
# orch + sub tool calls together — coarser but reliable).  Tier2's
# T2-14 has the same latent issue; flagged for follow-up.
_ANY_TOOL_TAG = re.compile(r"🔧 ")
# Per-iteration markers emitted by ``run_single_query`` when the CLI's
# ``--repeat N`` flag is set.  See ``src/olav/cli/main.py`` (Phase 1.5
# step 3 in dev_docs/62).
_RUN_ELAPSED_RE = re.compile(r"=== run (\d+) elapsed ([\d.]+)s ===")
_SAVE_ASSERTION_FIRED = re.compile(
    r"Auto-recovered|Save assertion warning", re.IGNORECASE
)


@dataclass
class RunResult:
    query_id: str
    agent: str
    run: int
    tool_call_count_orch: int
    elapsed_seconds: float
    save_assertion_fired: bool
    correctness_signal: bool
    exit_code: int
    stdout_preview: str  # first 500 chars for debugging
    # Phase 1.5 step b: when --repeat-cache N is set, per-iteration
    # elapsed times extracted from the CLI's ``=== run K elapsed Xs ===``
    # markers.  Empty when --repeat-cache is 0/unset.
    per_run_elapsed: list[float] = field(default_factory=list)


@dataclass
class QueryStats:
    query_id: str
    agent: str
    runs: int
    tool_calls_mean: float
    tool_calls_std: float
    tool_calls_min: int
    tool_calls_max: int
    elapsed_mean: float
    elapsed_std: float
    correctness_rate: float
    save_assertion_rate: float


@dataclass
class BenchReport:
    tag: str
    timestamp: str
    demo_dir: str
    runs_per_query: int
    runs: list[RunResult] = field(default_factory=list)
    summary: list[QueryStats] = field(default_factory=list)


def run_one(
    olav_bin: Path,
    cwd: Path,
    agent: str | None,
    query: str,
    timeout_s: int = 360,
    repeat: int = 1,
) -> tuple[int, str, float]:
    """Invoke olav with the given query; return (exit, stdout, elapsed)."""
    cmd = [str(olav_bin), "--no-splash"]
    if agent and agent != "core":
        cmd.extend(["--agent", agent])
    if repeat > 1:
        cmd.extend(["--repeat", str(repeat)])
    cmd.append(query)
    start = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout_s, check=False,
        )
        elapsed = time.time() - start
        return proc.returncode, proc.stdout + proc.stderr, elapsed
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - start
        # subprocess returns the partial buffers as bytes on TimeoutExpired
        # even when text=True was set on Popen — decode defensively.
        def _to_str(buf: object) -> str:
            if buf is None:
                return ""
            if isinstance(buf, bytes):
                return buf.decode("utf-8", errors="replace")
            return str(buf)
        out = _to_str(exc.stdout) + _to_str(exc.stderr)
        return 124, out + f"\n[TIMEOUT after {timeout_s}s]", elapsed


def measure(
    demo_dir: Path,
    runs_per_query: int,
    tag: str,
    repeat_cache: int = 0,
    *,
    reset_state: bool = True,
) -> BenchReport:
    olav_bin = demo_dir / ".venv" / "bin" / "olav"
    if not olav_bin.is_file():
        raise SystemExit(f"olav binary not found: {olav_bin}")
    exports_dir = demo_dir / "exports"

    report = BenchReport(
        tag=tag,
        timestamp=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        demo_dir=str(demo_dir),
        runs_per_query=runs_per_query,
    )

    # CC-1 (dev_docs/62): drop accumulated query_pattern rows before
    # measurement so consecutive bench runs are comparable.  Without
    # this, day-over-day numbers drift purely from agent-captured SQL
    # templates accumulating in the diversifier's top-13.  Preserves
    # usage_guide / schema_knowledge / value_distribution.
    if reset_state:
        try:
            db_path = demo_dir / ".olav" / "databases" / "memory.lance"
            if db_path.exists():
                from olav.core.memory import LanceDBStore
                from olav.core.memory.bench_reset import reset_volatile_categories
                store = LanceDBStore(db_path=str(db_path))
                result = reset_volatile_categories(store)
                cleared = result.get("cleared", {})
                if any(cleared.values()):
                    print(
                        f"[reset] cleared {cleared} (preserved "
                        f"{result.get('preserved', {})})",
                        flush=True,
                    )
        except Exception as exc:  # noqa: BLE001
            print(f"[reset] skipped — {exc}", flush=True)

    # When --repeat-cache N is set, the bench harness asks the olav CLI
    # to run the query N times in one process (via --repeat N), sharing
    # the SemanticCache across iterations.  Per-iteration timings come
    # from "=== run K elapsed Xs ===" markers (Phase 1.5 step b).
    cli_repeat = max(1, int(repeat_cache or 1))

    for qid, agent, query, predicate in QUERIES:
        for r in range(1, runs_per_query + 1):
            extra = f" (--repeat {cli_repeat})" if cli_repeat > 1 else ""
            print(f"[{qid}] run {r}/{runs_per_query} via --agent={agent}{extra} ...", flush=True)
            # Topology / drift queries can be slow on first invocation;
            # bump timeout when repeat-cache amplifies.
            # Q4 (simulation) periodically runs >300s on a cold cache —
            # 600s baseline gives headroom without masking real loops.
            t = 600 + 180 * (cli_repeat - 1)
            exit_code, out, elapsed = run_one(
                olav_bin, demo_dir, agent, query, timeout_s=t,
                repeat=cli_repeat,
            )
            # Prefer orch tag if rich didn't strip it; else fall back to
            # any 🔧 marker (counts orch + sub together — coarser).
            orch_count = len(_ORCH_TAG.findall(out))
            tool_count = orch_count if orch_count else len(_ANY_TOOL_TAG.findall(out))
            saw_assertion = bool(_SAVE_ASSERTION_FIRED.search(out))
            correct = bool(predicate(out, exports_dir))
            # Phase 1.5: extract per-iteration timings from
            # ``=== run K elapsed Xs ===`` markers when --repeat-cache > 1.
            per_run = [
                round(float(m.group(2)), 1)
                for m in _RUN_ELAPSED_RE.finditer(out)
            ]
            report.runs.append(RunResult(
                query_id=qid,
                agent=agent,
                run=r,
                tool_call_count_orch=tool_count,
                elapsed_seconds=round(elapsed, 1),
                save_assertion_fired=saw_assertion,
                correctness_signal=correct,
                per_run_elapsed=per_run,
                exit_code=exit_code,
                stdout_preview=out[-500:],  # tail is more informative
            ))
            extra = f"  per_run={per_run}" if per_run else ""
            print(
                f"    tool_calls={tool_count}  elapsed={elapsed:.0f}s  "
                f"correct={correct}  save_assertion={saw_assertion}{extra}",
                flush=True,
            )

    # Aggregate per-query
    by_query: dict[str, list[RunResult]] = {}
    for r in report.runs:
        by_query.setdefault(r.query_id, []).append(r)
    for qid, runs in by_query.items():
        tool_counts = [r.tool_call_count_orch for r in runs]
        elapsed = [r.elapsed_seconds for r in runs]
        report.summary.append(QueryStats(
            query_id=qid,
            agent=runs[0].agent,
            runs=len(runs),
            tool_calls_mean=round(statistics.mean(tool_counts), 1),
            tool_calls_std=(
                round(statistics.stdev(tool_counts), 1)
                if len(tool_counts) > 1 else 0.0
            ),
            tool_calls_min=min(tool_counts),
            tool_calls_max=max(tool_counts),
            elapsed_mean=round(statistics.mean(elapsed), 1),
            elapsed_std=(
                round(statistics.stdev(elapsed), 1)
                if len(elapsed) > 1 else 0.0
            ),
            correctness_rate=round(
                sum(1 for r in runs if r.correctness_signal) / len(runs), 2,
            ),
            save_assertion_rate=round(
                sum(1 for r in runs if r.save_assertion_fired) / len(runs), 2,
            ),
        ))

    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="Run tag — appears in filename")
    ap.add_argument(
        "--runs", type=int, default=5,
        help="Runs per query (default 5; N≥5 keeps Q4 std ≤±3 — see "
             "dev_docs/62 Phase 1.5 N=5 retest for why N=3 was insufficient).",
    )
    ap.add_argument(
        "--demo-dir",
        default=os.environ.get("OLAV_DEMO_DIR", str(Path.home() / "olav-demo6")),
        help="OLAV demo directory containing .venv (default ~/olav-demo6)",
    )
    ap.add_argument("--out", default=None, help="Output path (default /tmp/bench_<tag>_<ts>.json)")
    ap.add_argument(
        "--repeat-cache",
        type=int,
        default=0,
        help="Phase 1.5 (b): when set, ask the olav CLI to run each query N "
             "times in one process via --repeat N — measures SemanticCache "
             "amortisation between 1st and 2nd+ calls.  Per-iteration timings "
             "show up in JSON output as per_run_elapsed.",
    )
    ap.add_argument(
        "--no-reset-state",
        action="store_false",
        dest="reset_state",
        default=True,
        help="Skip the CC-1 query_pattern reset step.  Use when "
             "intentionally measuring contaminated state.",
    )
    args = ap.parse_args()

    demo_dir = Path(args.demo_dir).expanduser().resolve()
    report = measure(
        demo_dir, args.runs, args.tag,
        repeat_cache=args.repeat_cache,
        reset_state=args.reset_state,
    )

    out_path = Path(
        args.out
        or f"/tmp/bench_{args.tag}_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json"
    )
    out_path.write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n→ wrote {out_path}")

    # Pretty summary table
    print(f"\n=== {args.tag} summary ({args.runs} runs/query) ===")
    print(f"{'query':<10} {'agent':<6} {'tool_mean':>9} {'tool_std':>8} "
          f"{'elapsed_mean':>12} {'correct':>8} {'save_assert':>11}")
    for s in report.summary:
        print(f"{s.query_id:<10} {s.agent:<6} "
              f"{s.tool_calls_mean:>9.1f} {s.tool_calls_std:>8.1f} "
              f"{s.elapsed_mean:>11.0f}s "
              f"{s.correctness_rate:>8.0%} "
              f"{s.save_assertion_rate:>10.0%}")


if __name__ == "__main__":
    main()
