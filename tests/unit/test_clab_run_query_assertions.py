"""Unit tests for run_query_assertions.py.

run_query_sync is mocked — these tests validate the content-check logic,
JSON output, and substitution mechanics, NOT the LLM responses themselves.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

_SKILL_DIR = (
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab"
)
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from models import ScenarioQueryAssertion
from run_query_assertions import run_query_assertions

_QA_BGP = ScenarioQueryAssertion(
    agent="quick",
    description="BGP neighbor check",
    prompt="r1 的 BGP 邻居是谁？",
    expect_contains=["r2", "65002"],
    expect_not_contains=["没有找到"],
)


def _run(assertions, response_map: dict[str, str], tmp_path: Path, **kwargs):
    """Helper: mock run_query_sync per-agent and invoke run_query_assertions."""
    def fake_sync(prompt, agent="quick"):
        return response_map.get(agent, "")

    with patch("run_query_assertions.run_query_sync", side_effect=fake_sync):
        return run_query_assertions(
            test_run_id="t1",
            assertions=assertions,
            output_dir=tmp_path,
            **kwargs,
        )


def test_passes_when_response_contains_all_expected(tmp_path):
    result = _run(
        [_QA_BGP],
        {"quick": "r1 的 BGP 邻居是 r2，AS 65002，状态 Established"},
        tmp_path,
    )
    assert result.status == "passed"
    assert result.passed_count == 1
    assert result.assertions[0].matched == ["r2", "65002"]
    assert result.assertions[0].missing == []


def test_fails_when_expected_string_missing(tmp_path):
    result = _run(
        [_QA_BGP],
        {"quick": "r1 没有任何 BGP 邻居"},
        tmp_path,
    )
    assert result.status == "failed"
    assert result.assertions[0].passed is False
    assert "r2" in result.assertions[0].missing or "65002" in result.assertions[0].missing


def test_fails_when_banned_string_present(tmp_path):
    qa = ScenarioQueryAssertion(
        agent="quick",
        prompt="r1 的邻居",
        expect_contains=["r2"],
        expect_not_contains=["没有找到"],
    )
    result = _run(
        [qa],
        {"quick": "r2 已找到，但是没有找到其他邻居"},
        tmp_path,
    )
    assert result.status == "failed"
    assert "没有找到" in result.assertions[0].banned_found


def test_case_insensitive_matching(tmp_path):
    qa = ScenarioQueryAssertion(
        agent="quick",
        prompt="show bgp",
        expect_contains=["BGP", "Established"],
    )
    result = _run(
        [qa],
        {"quick": "bgp peers: established session with neighbor"},
        tmp_path,
    )
    assert result.status == "passed"


def test_multiple_assertions_mixed(tmp_path):
    qa_pass = ScenarioQueryAssertion(
        agent="quick", prompt="p1", expect_contains=["hello"]
    )
    qa_fail = ScenarioQueryAssertion(
        agent="olav", prompt="p2", expect_contains=["world"]
    )
    result = _run(
        [qa_pass, qa_fail],
        {"quick": "hello there", "olav": "nothing relevant"},
        tmp_path,
    )
    assert result.passed_count == 1
    assert result.failed_count == 1
    assert result.status == "failed"


def test_nodes_substitution_in_prompt(tmp_path):
    qa = ScenarioQueryAssertion(
        agent="quick",
        prompt="{nodes} 的 BGP 状态",
        expect_contains=["r1"],
    )
    captured = {}

    def fake_sync(prompt, agent="quick"):
        captured["prompt"] = prompt
        return "r1 BGP 状态正常"

    with patch("run_query_assertions.run_query_sync", side_effect=fake_sync):
        run_query_assertions(
            test_run_id="t1",
            assertions=[qa],
            output_dir=tmp_path,
            substitutions={"nodes": "r1,r2"},
        )

    assert captured["prompt"] == "r1,r2 的 BGP 状态"


def test_writes_json_output(tmp_path):
    result = _run([_QA_BGP], {"quick": "r2 AS 65002"}, tmp_path)
    out = tmp_path / "query_assertions.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["test_run_id"] == "t1"
    assert len(data["assertions"]) == 1
    assert data["assertions"][0]["agent"] == "quick"


def test_agent_exception_counts_as_failure(tmp_path):
    def fake_sync(prompt, agent="quick"):
        raise RuntimeError("connection refused")

    with patch("run_query_assertions.run_query_sync", side_effect=fake_sync):
        result = run_query_assertions(
            test_run_id="t1",
            assertions=[_QA_BGP],
            output_dir=tmp_path,
        )

    assert result.status == "failed"
    assert result.assertions[0].error is not None
    assert "connection refused" in result.assertions[0].error


def test_empty_assertions_returns_passed(tmp_path):
    result = _run([], {}, tmp_path)
    assert result.status == "passed"
    assert result.passed_count == 0
    assert result.failed_count == 0


def test_no_expect_contains_passes_always(tmp_path):
    """An assertion with no expected strings passes regardless of response."""
    qa = ScenarioQueryAssertion(agent="quick", prompt="anything")
    result = _run([qa], {"quick": "some response"}, tmp_path)
    assert result.assertions[0].passed is True
