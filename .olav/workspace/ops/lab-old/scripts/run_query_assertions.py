"""Run NL query assertions through OLAV agent chain.

This is the core E2E verification step: after data is collected in DuckDB,
we ask OLAV agents real natural-language questions and verify the answers
contain expected content.

This tests the full stack:
    NL prompt → Agent routing → SQL/CLI tool → DuckDB → LLM answer → content check

Unlike run_assertions.py (which bypasses the agent and queries SQL directly),
this module goes through the agent to catch LLM routing failures, tool call
failures, and schema mismatches that SQL-count checks cannot detect.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from models import (
    QueryAssertionResult,
    QueryAssertionsResult,
    ScenarioQueryAssertion,
)
from olav_invoke import run_query_sync


def _check_response(
    qa: ScenarioQueryAssertion,
    response: str,
) -> QueryAssertionResult:
    resp_lower = response.lower()

    matched = [s for s in qa.expect_contains if s.lower() in resp_lower]
    missing = [s for s in qa.expect_contains if s.lower() not in resp_lower]
    banned_found = [s for s in qa.expect_not_contains if s.lower() in resp_lower]

    passed = len(missing) == 0 and len(banned_found) == 0

    return QueryAssertionResult(
        description=qa.description or qa.prompt[:60],
        agent=qa.agent,
        prompt=qa.prompt,
        passed=passed,
        response_snippet=response[:300],
        matched=matched,
        missing=missing,
        banned_found=banned_found,
    )


def run_query_assertions(
    test_run_id: str,
    assertions: list[ScenarioQueryAssertion],
    output_dir: Path | None = None,
    substitutions: dict[str, str] | None = None,
) -> QueryAssertionsResult:
    """Invoke each NL query assertion through the OLAV agent and verify the response.

    Args:
        test_run_id: Used for naming the output file.
        assertions: List of NL query assertions from the scenario.
        output_dir: Where to write query_assertions.json (default: current dir).
        substitutions: Template variables to replace in prompts (e.g. {"nodes": "r1,r2"}).

    Returns:
        QueryAssertionsResult with all outcomes.
    """
    output_dir = Path(output_dir) if output_dir else Path(".")
    substitutions = substitutions or {}

    results: list[QueryAssertionResult] = []

    for qa in assertions:
        prompt = qa.prompt
        for key, val in substitutions.items():
            prompt = prompt.replace(f"{{{key}}}", val)

        try:
            response = run_query_sync(prompt, agent=qa.agent)
            # Build a temporary assertion with the substituted prompt for the check
            qa_resolved = ScenarioQueryAssertion(
                agent=qa.agent,
                prompt=prompt,
                description=qa.description,
                expect_contains=qa.expect_contains,
                expect_not_contains=qa.expect_not_contains,
            )
            result = _check_response(qa_resolved, response)
        except Exception as exc:
            result = QueryAssertionResult(
                description=qa.description or prompt[:60],
                agent=qa.agent,
                prompt=prompt,
                passed=False,
                response_snippet="",
                matched=[],
                missing=qa.expect_contains,
                banned_found=[],
                error=str(exc),
            )

        results.append(result)

    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count

    output = QueryAssertionsResult(
        test_run_id=test_run_id,
        assertions=results,
        passed_count=passed_count,
        failed_count=failed_count,
        timestamp=datetime.now(UTC).isoformat(),
        status="passed" if failed_count == 0 else "failed",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "query_assertions.json").write_text(output.model_dump_json(indent=2))

    return output
