"""Parser-learner sub-agent E2E tests.

Covers the netops/learner sub-agent (formerly top-level command_learner,
folded back into netops on 2026-05-20 — textfsm learning is netops-domain
work, not a platform capability):
  - Tools: learn_commands, cmd_learn, draft_parser, validate_parser, freeze_parser

Structural tests (no LLM) run always.
LLM tests are gated by LEARNER_E2E_ENABLED=1.

Usage:
    # structural only:
    uv run pytest tests/e2e/test_command_learner_e2e.py -v

    # with LLM:
    LEARNER_E2E_ENABLED=1 uv run pytest tests/e2e/test_command_learner_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_OLAV_CMD = [sys.executable, "-m", "olav"]
_WORKSPACE = _ROOT / ".olav" / "workspace" / "netops" / "learner"

_LLM_ENABLED = os.environ.get("LEARNER_E2E_ENABLED", "").strip() == "1"
_LLM_SKIP = pytest.mark.skipif(
    not _LLM_ENABLED,
    reason="LLM-gated: set LEARNER_E2E_ENABLED=1 to run learner live tests",
)


def _run_agent(prompt: str, timeout: int = 180) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        _OLAV_CMD + ["--agent", "netops", prompt],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=_ROOT,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return subprocess.CompletedProcess(proc.args, -1, stdout or "", stderr or "")
    except BaseException:
        try:
            proc.kill()
            proc.communicate()
        except Exception:
            pass
        raise


# ── Structural (no LLM) ──────────────────────────────────────────────────────


class TestLearnerSubagentStructure:
    """netops/learner sub-agent workspace structure — no LLM required."""

    def test_skill_md_exists(self):
        assert (_WORKSPACE / "SKILL.md").is_file(), f"learner SKILL.md missing at {_WORKSPACE}"

    def test_skill_md_declares_name_learner(self):
        text = (_WORKSPACE / "SKILL.md").read_text(encoding="utf-8")
        assert "name: learner" in text

    def test_skill_md_has_agent_type_api(self):
        text = (_WORKSPACE / "SKILL.md").read_text(encoding="utf-8")
        assert "agent_type: api" in text

    def test_skill_md_has_temperature_zero(self):
        text = (_WORKSPACE / "SKILL.md").read_text(encoding="utf-8")
        assert "temperature: 0.0" in text, (
            "learner must have temperature: 0.0 for deterministic parsing"
        )

    def test_skill_md_declares_learn_commands(self):
        text = (_WORKSPACE / "SKILL.md").read_text(encoding="utf-8")
        assert "learn_commands" in text

    def test_skill_md_declares_cmd_learn(self):
        text = (_WORKSPACE / "SKILL.md").read_text(encoding="utf-8")
        assert "cmd_learn" in text

    def test_learn_commands_script_exists(self):
        # migrated from tools/ → scripts/ in rev ~295
        script = _WORKSPACE / "scripts" / "learn_commands.py"
        assert script.is_file(), f"learn_commands.py missing at {script}"

    def test_cmd_learn_script_exists(self):
        # migrated from tools/ → scripts/ in rev ~295
        script = _WORKSPACE / "scripts" / "cmd_learn.py"
        assert script.is_file(), f"cmd_learn.py missing at {script}"

    def test_dsl_choice_rules_reference_exists(self):
        ref = _WORKSPACE / "references" / "DSL_CHOICE_RULES.md"
        assert ref.is_file(), f"DSL_CHOICE_RULES.md missing at {ref}"

    def test_frozen_layout_reference_exists(self):
        ref = _WORKSPACE / "references" / "FROZEN_LAYOUT.md"
        assert ref.is_file(), f"FROZEN_LAYOUT.md missing at {ref}"

    def test_netops_listed_in_olav_list(self):
        result = subprocess.run(
            _OLAV_CMD + ["list"],
            capture_output=True, text=True, timeout=30, cwd=_ROOT,
        )
        assert "netops" in result.stdout + result.stderr, (
            "'netops' not found in olav list output"
        )


# ── Behaviour (LLM required) ─────────────────────────────────────────────────


@_LLM_SKIP
@pytest.mark.timeout(180)
class TestLearnerLearnCmd:
    """netops/learner: /learn_cmd invocation with a simple command."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent(
                '/learn_cmd cisco_ios "show version"', timeout=150
            )
        return cls._result

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies")
    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, (
            f"netops /learn_cmd failed:\n{r.stdout}\n{r.stderr}"
        )

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies")
    def test_mentions_parser_or_template(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(kw in out.lower() for kw in (
            "parser", "template", "textfsm", "frozen", "learn", "draft"
        )), f"Response does not mention parser activity:\n{out[:600]}"
