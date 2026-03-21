"""
run_session.py — Session-based E2E orchestrator.

Unlike run_e2e.py (which deploys + tests + destroys per scenario),
run_session.py manages a long-lived lab topology:

  1. ensure_lab_running()  — idempotent deploy via ContainerLab API
  2. inject_session_hosts() — register all nodes in Nornir hosts.yaml
  3. collect_session_baseline() — OLAV collection queries defined in SESSION.yaml
  4. run_suite(suite)  — iterate test cases in dependency order
  5. report_results()  — write SessionResult + update references/results.duckdb

Usage:
    uv run python .agent/skills/containerlab-e2e/scripts/run_session.py lab_sessions/enterprise_dual_site/SESSION.yaml
    uv run python .agent/skills/containerlab-e2e/scripts/run_session.py lab_sessions/enterprise_dual_site/SESSION.yaml --suite L2_access
    uv run python .agent/skills/containerlab-e2e/scripts/run_session.py lab_sessions/enterprise_dual_site/SESSION.yaml --destroy-on-finish
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime, timezone
from pathlib import Path

import yaml

# ── Skill-relative imports ────────────────────────────────────────────────────
_SKILL_ROOT = Path(__file__).parent
sys.path.insert(0, str(_SKILL_ROOT))

from models import (
    AssertionsResult,
    LabSession,
    QueryAssertionsResult,
    ScenarioQueryAssertion,
    SessionNode,
    SessionResult,
    SuiteResult,
    TestCase,
    TestCaseResult,
    TestSuite,
)
from run_assertions import run_assertions
from run_query_assertions import run_query_assertions
from track_coverage import track_coverage

# ── OLAV core imports (available at runtime) ──────────────────────────────────
try:
    from olav.agents.olav_invoke import run_query_sync  # noqa: F401 — used by run_query_assertions
    from olav.core.config import get_settings
except ImportError:
    pass  # Allow import in unit-test contexts without full OLAV stack


# ─────────────────────────────────────────────────────────────────────────────
#  Loaders
# ─────────────────────────────────────────────────────────────────────────────

def load_session(session_yaml: Path) -> LabSession:
    data = yaml.safe_load(session_yaml.read_text())
    nodes = {
        name: SessionNode(**node_data)
        for name, node_data in (data.get("nodes") or {}).items()
    }
    from models import ScenarioQuery
    collect_queries = [ScenarioQuery(**q) for q in (data.get("collect_queries") or [])]
    return LabSession(
        session=data["session"],
        description=data.get("description", ""),
        topology_file=data["topology_file"],
        nodes=nodes,
        collect_queries=collect_queries,
        test_suites=data.get("test_suites", []),
        readiness=data.get("readiness", {}),
    )


def load_suite(suite_yaml: Path) -> TestSuite:
    data = yaml.safe_load(suite_yaml.read_text())
    preconditions = [
        ScenarioQueryAssertion(**q) for q in (data.get("precondition_queries") or [])
    ]
    return TestSuite(
        suite=data["suite"],
        description=data.get("description", ""),
        depends_on_session=data["depends_on_session"],
        layer=data.get("layer", ""),
        depends_on_suites=data.get("depends_on_suites", []),
        precondition_queries=preconditions,
        test_cases=data.get("test_cases", []),
    )


def load_test_case(tc_yaml: Path) -> TestCase:
    from models import ScenarioAssertion, ScenarioQuery, ScenarioQueryAssertion

    data = yaml.safe_load(tc_yaml.read_text())

    def _load_queries(key: str) -> list[ScenarioQuery]:
        return [ScenarioQuery(**q) for q in (data.get(key) or [])]

    def _load_nl_assertions(key: str) -> list[ScenarioQueryAssertion]:
        return [ScenarioQueryAssertion(**q) for q in (data.get(key) or [])]

    return TestCase(
        name=data["name"],
        description=data.get("description", ""),
        queries=_load_queries("queries"),
        assertions=[ScenarioAssertion(**a) for a in (data.get("assertions") or [])],
        query_assertions=_load_nl_assertions("query_assertions"),
        pre_fault_queries=_load_queries("pre_fault_queries"),
        pre_fault_assertions=_load_nl_assertions("pre_fault_assertions"),
        post_fault_queries=_load_queries("post_fault_queries"),
        post_fault_assertions=_load_nl_assertions("post_fault_assertions"),
        fault=data.get("fault"),
        recover=data.get("recover"),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Lab lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def _check_lab_running(lab_name: str) -> bool:
    """
    Return True if the ContainerLab topology is already deployed.
    Checks via the ContainerLab API (must be running on localhost:8080).
    Falls back to docker-inspect if the API is unavailable.
    """
    import subprocess

    try:
        import requests

        resp = requests.get("http://localhost:8080/api/v1/labs", timeout=5)
        if resp.ok:
            labs = resp.json()
            # ContainerLab returns lab names normalised (spaces → dashes)
            return any(
                lab.get("name", "").lower().replace(" ", "-") == lab_name.lower()
                for lab in (labs if isinstance(labs, list) else labs.get("labs", []))
            )
    except Exception:
        pass  # API not available, fall back to docker

    # Docker fallback: check for a container named <lab_name>-<any_node>
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    prefix = f"clab-{lab_name}-"
    return any(line.startswith(prefix) for line in result.stdout.splitlines())


def ensure_lab_running(session: LabSession, session_dir: Path, deploy: bool = True) -> bool:
    """
    Idempotent deploy. Returns True if lab was already running (no deploy needed).
    If deploy=False, raises RuntimeError when the lab is not running.
    """
    from compile_scenario import compile_scenario  # skill-local module
    from deploy_lab import deploy_lab  # skill-local module

    topology_path = session_dir / session.topology_file
    lab_name = topology_path.stem.replace("_", "-")  # enterprise_dual_site → enterprise-dual-site

    if _check_lab_running(lab_name):
        print(f"[session] Lab '{lab_name}' already running — skipping deploy")
        return True

    if not deploy:
        raise RuntimeError(
            f"Lab '{lab_name}' is not running and deploy=False. "
            "Start the lab first or remove --no-deploy flag."
        )

    print(f"[session] Deploying lab '{lab_name}' from {topology_path}")
    plan = compile_scenario(topology_path)
    result = asyncio.run(deploy_lab(plan))
    if result.status != "success":
        raise RuntimeError(f"Lab deploy failed: {result.error}")
    return False


def inject_session_hosts(session: LabSession) -> None:
    """Register all session nodes in Nornir hosts.yaml via OLAV InjectHosts."""
    from inject_hosts import inject_hosts  # skill-local module

    print(f"[session] Injecting {len(session.nodes)} hosts into Nornir inventory")
    inject_hosts(session.nodes)


# ─────────────────────────────────────────────────────────────────────────────
#  Collection
# ─────────────────────────────────────────────────────────────────────────────

def collect_session_baseline(session: LabSession, run_id: str) -> None:
    """Run SESSION.yaml collect_queries once after deploy."""
    from run_query_assertions import _invoke_agent  # internal

    node_names = ",".join(session.nodes.keys())
    for cq in session.collect_queries:
        prompt = cq.prompt.replace("{nodes}", node_names)
        print(f"[collect] [{cq.agent}] {prompt[:80]}…")
        try:
            _invoke_agent(prompt, agent=cq.agent)
        except Exception as exc:
            print(f"[collect] WARNING: collection failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Suite runner
# ─────────────────────────────────────────────────────────────────────────────

def _check_preconditions(
    preconditions: list[ScenarioQueryAssertion],
    run_id: str,
    output_dir: Path,
) -> bool:
    """Return True if all precondition NL assertions pass."""
    if not preconditions:
        return True
    result = run_query_assertions(run_id, preconditions, output_dir=output_dir)
    if result.status != "passed":
        print(f"[suite] Preconditions FAILED ({result.failed_count} / {len(preconditions)})")
        for r in result.assertions:
            if not r.passed:
                print(f"  ✗ {r.description}: missing={r.missing}")
    return result.status == "passed"


def run_test_case(
    tc: TestCase,
    run_id: str,
    output_dir: Path,
) -> TestCaseResult:
    """Run a single TestCase: queries → SQL assertions → NL assertions."""
    from run_query_assertions import run_query_assertions as rqa

    print(f"  [tc] {tc.name}")
    tc_dir = output_dir / tc.name
    tc_dir.mkdir(parents=True, exist_ok=True)

    sql_result: AssertionsResult | None = None
    nl_result: QueryAssertionsResult | None = None

    # SQL assertions
    if tc.assertions:
        try:
            sql_result = run_assertions(
                test_run_id=run_id,
                assertions=tc.assertions,
                output_dir=tc_dir,
            )
        except Exception as exc:
            return TestCaseResult(
                name=tc.name,
                status="error",
                error=str(exc),
            )

    # NL query assertions
    if tc.query_assertions:
        nl_result = rqa(run_id, tc.query_assertions, output_dir=tc_dir)

    # Determine status
    sql_ok = sql_result is None or sql_result.status == "passed"
    nl_ok = nl_result is None or nl_result.status == "passed"
    status: str = "passed" if (sql_ok and nl_ok) else "failed"

    return TestCaseResult(
        name=tc.name,
        sql_result=sql_result,
        nl_result=nl_result,
        status=status,  # type: ignore[arg-type]
    )


def run_suite(
    suite: TestSuite,
    suite_dir: Path,
    passed_suites: set[str],
    run_id: str,
    output_dir: Path,
) -> SuiteResult:
    """Run all test cases in a suite, respecting inter-suite dependencies."""
    timestamp = datetime.now(UTC).isoformat()
    results: list[TestCaseResult] = []

    # Check inter-suite dependencies
    for dep in suite.depends_on_suites:
        if dep not in passed_suites:
            print(f"[suite] {suite.suite}: SKIPPED — dependency '{dep}' did not pass")
            return SuiteResult(
                suite=suite.suite,
                test_cases=[
                    TestCaseResult(name=tc, status="skipped")
                    for tc in suite.test_cases
                ],
                passed_count=0,
                failed_count=0,
                skipped_count=len(suite.test_cases),
                status="skipped",
                timestamp=timestamp,
            )

    # Check preconditions
    suite_out = output_dir / suite.suite
    suite_out.mkdir(parents=True, exist_ok=True)
    if not _check_preconditions(suite.precondition_queries, run_id, suite_out):
        print(f"[suite] {suite.suite}: SKIPPED — preconditions failed")
        return SuiteResult(
            suite=suite.suite,
            test_cases=[TestCaseResult(name=tc, status="skipped") for tc in suite.test_cases],
            passed_count=0,
            failed_count=0,
            skipped_count=len(suite.test_cases),
            status="skipped",
            timestamp=timestamp,
        )

    print(f"[suite] {suite.suite} — {len(suite.test_cases)} test case(s)")
    for tc_name in suite.test_cases:
        tc_yaml = suite_dir / tc_name
        if not tc_yaml.exists():
            print(f"  [tc] WARNING: {tc_yaml} not found — skipping")
            results.append(TestCaseResult(name=tc_name, status="skipped"))
            continue
        tc = load_test_case(tc_yaml)
        result = run_test_case(tc, run_id, suite_out)
        results.append(result)
        icon = "✓" if result.status == "passed" else "✗"
        print(f"  {icon} {tc.name}: {result.status}")

    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    status = "passed" if failed == 0 and passed > 0 else "failed"

    return SuiteResult(
        suite=suite.suite,
        test_cases=results,
        passed_count=passed,
        failed_count=failed,
        skipped_count=skipped,
        status=status,  # type: ignore[arg-type]
        timestamp=timestamp,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_session(
    session_yaml: Path,
    suite_filter: str | None = None,
    no_deploy: bool = False,
    destroy_on_finish: bool = False,
) -> SessionResult:
    run_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now(UTC).isoformat()
    session_dir = session_yaml.parent
    evidence_dir = _SKILL_ROOT / "evidence" / f"session_{session_dir.name}_{run_id}"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'═' * 60}")
    print(f"  OLAV Session Runner  |  run_id={run_id}")
    print(f"  {session_yaml.name}")
    print(f"{'═' * 60}\n")

    session = load_session(session_yaml)

    # Step 1: Ensure lab is running (idempotent deploy)
    ensure_lab_running(session, session_dir, deploy=not no_deploy)

    # Step 2: Inject all nodes into Nornir
    inject_session_hosts(session)

    # Step 3: Session-level baseline collection
    collect_session_baseline(session, run_id)

    # Step 4: Run suites in declared order
    suite_results: list[SuiteResult] = []
    passed_suites: set[str] = set()

    suite_paths: list[Path] = []
    if suite_filter:
        # --suite L2_access → find matching suite YAML
        for ts in session.test_suites:
            p = session_dir.parent.parent / "test_suites" / ts
            if not p.exists():
                p = _SKILL_ROOT / "test_suites" / ts
            if p.exists() and suite_filter.lower() in p.name.lower():
                suite_paths.append(p)
    else:
        for ts in session.test_suites:
            # Resolve relative to test_suites/ or session_dir parents
            p = _SKILL_ROOT / "test_suites" / ts
            if not p.exists():
                p = session_dir / ts
            suite_paths.append(p)

    for suite_yaml_path in suite_paths:
        if not suite_yaml_path.exists():
            print(f"[session] WARNING: suite YAML not found: {suite_yaml_path}")
            continue
        suite = load_suite(suite_yaml_path)
        suite_dir = suite_yaml_path.parent
        result = run_suite(suite, suite_dir, passed_suites, run_id, evidence_dir)
        suite_results.append(result)
        if result.status == "passed":
            passed_suites.add(suite.suite)

    passed = sum(1 for s in suite_results if s.status == "passed")
    failed = sum(1 for s in suite_results if s.status == "failed")
    final_status = "passed" if failed == 0 else "failed"

    session_result = SessionResult(
        session=session.session,
        run_id=run_id,
        suites=suite_results,
        passed_count=passed,
        failed_count=failed,
        status=final_status,  # type: ignore[arg-type]
        timestamp=timestamp,
    )

    # Write evidence
    result_path = evidence_dir / "session_result.json"
    result_path.write_text(session_result.model_dump_json(indent=2))

    # Persist to results DB
    try:
        from track_coverage import E2E_RESULTS_DB, _append_session_to_db

        _append_session_to_db(session_result, db_path=E2E_RESULTS_DB)
    except Exception as exc:
        print(f"[session] WARNING: could not write to results DB: {exc}")

    print(f"\n{'─' * 60}")
    print(f"  Result: {final_status.upper()}  |  suites passed={passed}  failed={failed}")
    print(f"  Evidence: {result_path}")
    print(f"{'─' * 60}\n")

    if destroy_on_finish:
        from compile_scenario import compile_scenario  # skill-local module
        from deploy_lab import deploy_lab  # skill-local module
        from destroy_lab import destroy_lab  # skill-local module

        topology_path = session_dir / session.topology_file
        print("[session] Destroying lab (--destroy-on-finish)")
        deploy_result = asyncio.run(deploy_lab(compile_scenario(topology_path)))
        asyncio.run(destroy_lab(deploy_result, output_dir=evidence_dir))

    return session_result


def main() -> None:
    parser = argparse.ArgumentParser(description="OLAV Session-based E2E runner")
    parser.add_argument("session_yaml", type=Path, help="Path to SESSION.yaml")
    parser.add_argument("--suite", help="Run only the named suite (e.g. L2_access)")
    parser.add_argument("--no-deploy", action="store_true", help="Fail if lab not already running")
    parser.add_argument("--destroy-on-finish", action="store_true", help="Destroy lab after tests")
    args = parser.parse_args()

    result = run_session(
        session_yaml=args.session_yaml,
        suite_filter=args.suite,
        no_deploy=args.no_deploy,
        destroy_on_finish=args.destroy_on_finish,
    )
    sys.exit(0 if result.status == "passed" else 1)


if __name__ == "__main__":
    main()
