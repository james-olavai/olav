#!/usr/bin/env python3
"""Simplified E2E orchestrator using OLAV CLI."""

from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from collect_artifacts import collect_artifacts
from compile_scenario import compile_scenario
from configure_device import configure_device
from deploy_lab import deploy_lab
from destroy_lab import destroy_lab
from hosts_inject import cleanup_hosts, inject_hosts, restore_hosts
from models import ExecutionPlan, ScenarioQueryAssertion
from olav_invoke import run_query_sync
from run_assertions import run_assertions
from run_query_assertions import run_query_assertions
from track_coverage import track_coverage
from wait_readiness import wait_readiness

EVIDENCE_BASE = _HERE / "evidence"


def _banner(step: int, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  [{step}/9] {title}")
    print(f"{'='*60}")


async def run_e2e(
    scenario_path: Path,
    config_dir: Path | None = None,
    dry_run_only: bool = False,
    skip_destroy: bool = False,
) -> int:
    """Run simplified E2E test using OLAV CLI for data collection."""

    # Step 1: Compile scenario
    _banner(1, "compile_scenario")
    try:
        plan = compile_scenario(scenario_path, evidence_base=EVIDENCE_BASE)
        print(f"  ✓ execution plan compiled: {plan.test_run_id}")
    except Exception as exc:
        print(f"  ✗ compile_scenario failed: {exc}")
        traceback.print_exc()
        return 1

    evidence_dir = EVIDENCE_BASE / plan.test_run_id
    config_dir = config_dir or _HERE / "configs"

    # Step 2: Deploy lab
    _banner(2, "deploy_lab")
    try:
        deploy_result = await deploy_lab(plan)
        if deploy_result.status != "success":
            print(f"  ✗ deploy failed: {deploy_result.error}")
            return 1
        print(f"  ✓ lab deployed: {deploy_result.lab_name}")
    except Exception as exc:
        print(f"  ✗ deploy_lab exception: {exc}")
        traceback.print_exc()
        return 1

    if dry_run_only:
        print("\n  --dry-run-only flag set; stopping here (lab deployed but not configured)")
        return 0

    # Step 3: Configure device (dry-run)
    _banner(3, "configure_device (dry-run)")
    try:
        await configure_device(
            plan,
            deploy_result,
            config_dir=config_dir,
            dry_run=True,
            output_dir=evidence_dir,
        )
        print("  ✓ config preview generated")
    except Exception as exc:
        print(f"  ✗ configure dry-run exception: {exc}")
        traceback.print_exc()

    # Step 4: Configure device (apply)
    _banner(4, "configure_device (apply)")
    try:
        config_result = await configure_device(
            plan,
            deploy_result,
            config_dir=config_dir,
            dry_run=False,
            output_dir=evidence_dir,
        )
        if config_result.status != "success":
            print(f"  ✗ configure failed: {config_result.error}")
            if not skip_destroy:
                await destroy_lab(deploy_result)
            return 1
        print(f"  ✓ config applied to {len(config_result.nodes)} nodes")
    except Exception as exc:
        print(f"  ✗ configure_device exception: {exc}")
        traceback.print_exc()
        if not skip_destroy:
            await destroy_lab(deploy_result)
        return 1

    # Step 5: Wait for readiness
    _banner(5, "wait_readiness")
    try:
        ready_result = await wait_readiness(
            plan,
            deploy_result,
            output_dir=evidence_dir,
        )
        if ready_result.status == "timeout":
            print("  ⚠ protocol convergence timeout")
        else:
            print(f"  ✓ {len([n for n in ready_result.nodes.values() if n.ssh_reachable])} nodes SSH-ready")
    except Exception as exc:
        print(f"  ✗ wait_readiness exception: {exc}")
        traceback.print_exc()

    # Step 6: Inject hosts into OLAV's nornir inventory
    _banner(6, "inject_hosts")
    original_hosts = None
    try:
        original_hosts = inject_hosts(deploy_result)
    except Exception as exc:
        print(f"  ✗ inject_hosts failed (fatal): {exc}")
        await destroy_lab(deploy_result)
        return 1

    # Step 7: Collect via OLAV CLI (natural language, per-scenario queries)
    _banner(7, "olav collect (natural language)")
    node_names = ",".join(plan.nodes.keys())
    queries = plan.queries
    if not queries:
        # Fallback if scenario has no queries defined
        from models import ScenarioQuery
        queries = [ScenarioQuery(
            agent="ops",
            description="Default collect: routing protocols + LLDP topology",
            prompt=f"从 {node_names} 采集所有路由协议邻接关系和 LLDP 拓扑",
        )]
    for i, q in enumerate(queries, 1):
        prompt = q.prompt.replace("{nodes}", node_names)
        print(f"  [{i}/{len(queries)}] agent={q.agent} — {q.description or prompt[:60]}")
        try:
            result = run_query_sync(prompt, agent=q.agent)
            print(f"    ✓ {result[:120]}...")
        except Exception as exc:
            print(f"    ⚠ query failed (non-fatal): {exc}")
            traceback.print_exc()

    # Step 8: Run SQL count assertions on main.duckdb (structural verification)
    _banner(8, "run_assertions (SQL)")
    assert_result = None
    try:
        assertions_raw = plan.assertions
        from models import ScenarioAssertion

        assertions = [ScenarioAssertion.model_validate(a) for a in assertions_raw]
        assert_result = run_assertions(
            test_run_id=plan.test_run_id,
            assertions=assertions,
            db_path=None,  # Uses MAIN_DB_PATH by default
            output_dir=evidence_dir,
        )
        status_icon = "✓" if assert_result.status == "passed" else "✗"
        print(f"  {status_icon} assertions: {assert_result.passed_count} passed, {assert_result.failed_count} failed")
    except Exception as exc:
        print(f"  ✗ run_assertions exception: {exc}")
        traceback.print_exc()

    # Step 8b: NL query assertions through OLAV agent chain (THE CORE E2E TEST)
    # This exercises: NL → Agent routing → Tool(SQL) → DuckDB → LLM answer → content check
    _banner(9, "run_query_assertions (NL agent chain)")
    query_assert_result = None
    if plan.query_assertions:
        node_names = ",".join(plan.nodes.keys())
        try:
            query_assert_result = run_query_assertions(
                test_run_id=plan.test_run_id,
                assertions=plan.query_assertions,
                output_dir=evidence_dir,
                substitutions={"nodes": node_names, "run_id": plan.test_run_id},
            )
            status_icon = "✓" if query_assert_result.status == "passed" else "✗"
            print(
                f"  {status_icon} query assertions: "
                f"{query_assert_result.passed_count} passed, "
                f"{query_assert_result.failed_count} failed"
            )
            for r in query_assert_result.assertions:
                icon = "✓" if r.passed else "✗"
                print(f"    {icon} [{r.agent}] {r.description}")
                if not r.passed:
                    if r.missing:
                        print(f"       missing: {r.missing}")
                    if r.banned_found:
                        print(f"       banned found: {r.banned_found}")
        except Exception as exc:
            print(f"  ✗ run_query_assertions exception: {exc}")
            traceback.print_exc()
    else:
        print("  ⚠ no query_assertions defined in scenario — skipping agent chain test")

    # Collect artifacts
    try:
        art_result = collect_artifacts(
            test_run_id=plan.test_run_id,
            evidence_dir=evidence_dir,
        )
        print(f"  ✓ artifacts.json written ({len(art_result.artifacts)} items)")
    except Exception as exc:
        print(f"  ✗ collect_artifacts exception: {exc}")

    # Step 10: Cleanup, destroy, and track coverage
    _banner(10, "cleanup + destroy + track_coverage")
    try:
        if original_hosts:
            restore_hosts(original_hosts)
        cleanup_hosts(plan.test_run_id)
    except Exception as exc:
        print(f"  ⚠ cleanup failed (non-fatal): {exc}")

    if not skip_destroy:
        try:
            destroy_result = await destroy_lab(deploy_result)
            if destroy_result.status == "success":
                print("  ✓ lab destroyed")
            else:
                print(f"  ⚠ destroy partial: {destroy_result.error}")
        except Exception as exc:
            print(f"  ✗ destroy_lab exception: {exc}")
            traceback.print_exc()

    # Track coverage
    try:
        platforms = list({n.platform for n in deploy_result.nodes.values()})
        # Both SQL assertions AND NL query assertions must pass
        sql_ok = assert_result.status == "passed" if assert_result else None
        nl_ok = query_assert_result.status == "passed" if query_assert_result else None
        if sql_ok is False or nl_ok is False:
            final_result = "failed"
        elif sql_ok is True or nl_ok is True:
            final_result = "passed"
        else:
            final_result = "unknown"
        track_coverage(
            test_run_id=plan.test_run_id,
            scenario_name=plan.scenario_name,
            topology_file=plan.topology_file,
            platforms=platforms,
            layers_tested=plan.metadata.layers,
            features_tested=plan.metadata.features,
            commands_expected=plan.metadata.commands_expected,
            node_count=len(plan.nodes),
            link_count=len(plan.links),
            result=final_result,
            evidence_path=str(evidence_dir),
            collect_method="olav_cli",
        )
        print("  ✓ coverage updated")
    except Exception as exc:
        print(f"  ✗ track_coverage exception: {exc}")

    # Final summary
    final_status = final_result if "final_result" in dir() else "unknown"
    print(f"\n{'='*60}")
    print(f"  E2E result: {final_status.upper()}")
    if assert_result:
        print(f"  SQL assertions  : {assert_result.passed_count}✓  {assert_result.failed_count}✗")
    if query_assert_result:
        print(f"  NL assertions   : {query_assert_result.passed_count}✓  {query_assert_result.failed_count}✗")
    print(f"  evidence        : {evidence_dir}")
    print(f"{'='*60}\n")

    return 0 if final_status == "passed" else 1


async def main_async():
    parser = argparse.ArgumentParser(
        description="Simplified OLAV ContainerLab E2E orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python run_e2e_new.py \\
      --scenario scenarios/bgp_2node.yaml

  uv run python run_e2e_new.py \\
      --scenario scenarios/bgp_2node.yaml \\
      --skip-destroy
        """,
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        required=True,
        help="Path to scenario YAML file",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Config directory (default: ./configs)",
    )
    parser.add_argument(
        "--dry-run-only",
        action="store_true",
        help="Stop after config dry-run (no actual lab)",
    )
    parser.add_argument(
        "--skip-destroy",
        action="store_true",
        help="Keep lab alive after test (for debugging)",
    )

    args = parser.parse_args()

    # Ensure scenario exists
    if not args.scenario.exists():
        print(f"Scenario file not found: {args.scenario}", file=sys.stderr)
        return 1

    return await run_e2e(
        args.scenario,
        config_dir=args.config_dir,
        dry_run_only=args.dry_run_only,
        skip_destroy=args.skip_destroy,
    )


def main():
    try:
        exit_code = asyncio.run(main_async())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n[interrupted]")
        sys.exit(130)
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
