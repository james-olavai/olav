"""Every test path a CI workflow names must exist and actually hold tests.

Found by inspection on 2026-08-06, after a CI review turned up two independent
instances of the same rot — CI confidently running things that verify nothing:

1. `.github/workflows/test.yml` listed `tests/e2e/test_phase{1..4}_*.py` in its
   no-LLM job. Those four files had been reduced to redirect stubs when their
   content moved to `tests/gates/`:

       \"\"\"Phase 1 Gate: Collection Capability Verification — REDIRECTED.\"\"\"
       # Tests moved to tests/gates/test_gate_phase1_collection.py

   pytest collects zero tests from them and exits 0. The job had been green,
   and empty, for as long as the files had been stubs.

2. `.gitea/workflows/ci.yml` — the *merge gate* — named no gate suite at all,
   which is how `olav-netops/tests/gates/` stayed red for months.

A green CI step over an empty file is worse than a missing one: it reports
success. This gate reads both forges' workflows, extracts every `tests/...py`
path they hand to pytest, and checks each one exists and defines at least one
test. It is deterministic and needs neither a runner nor a network.

Directory targets (`tests/unit/`, `tests/gates/`) are checked for existence and
non-emptiness too, but not for per-file content — a directory that collects
nothing is the same defect one level up.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_WORKFLOWS = [
    REPO / ".gitea" / "workflows" / "ci.yml",
    REPO / ".github" / "workflows" / "test.yml",
]

# `tests/...` or `olav-netops/tests/...`, ending in .py or a directory slash.
_TARGET_RE = re.compile(r"(?<![\w./-])((?:[\w.-]+/)?tests/[\w./-]*?(?:\.py|/))")


def _targets(workflow: Path) -> set[str]:
    """Paths the workflow hands to pytest.

    Read from the raw text rather than the parsed YAML: the run steps are
    shell scripts with line continuations, so the paths are inside opaque
    scalar blocks either way, and a regex over the text needs no assumptions
    about how a step spells its invocation.

    Comment lines are dropped — several explain the layout by naming paths
    (`tests/governance/ -m netops`) that the job does not itself run.
    """
    found: set[str] = set()
    for line in workflow.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        found.update(_TARGET_RE.findall(line))
    return found


def _test_count(path: Path) -> int:
    """Tests defined at any level of the module — functions and methods."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    )


def _all_targets() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for wf in _WORKFLOWS:
        if not wf.exists():
            continue
        for t in sorted(_targets(wf)):
            out.append((wf.name, t))
    return out


_TARGETS = _all_targets()


def test_workflows_were_actually_read():
    """A silent regex miss would make every check below vacuous."""
    assert _WORKFLOWS[0].exists(), "gitea ci.yml missing — it is the merge gate"
    assert len(_TARGETS) >= 6, (
        f"only {len(_TARGETS)} pytest targets found across the workflows; the "
        "extraction pattern has probably stopped matching"
    )


@pytest.mark.parametrize("workflow,target", _TARGETS, ids=[f"{w}:{t}" for w, t in _TARGETS])
def test_ci_target_exists(workflow, target):
    path = REPO / target
    assert path.exists(), (
        f"{workflow} runs pytest on {target}, which does not exist — the step "
        f"either errors or silently passes over nothing"
    )


@pytest.mark.parametrize(
    "workflow,target",
    [(w, t) for w, t in _TARGETS if t.endswith(".py")],
    ids=[f"{w}:{t}" for w, t in _TARGETS if t.endswith(".py")],
)
def test_ci_target_file_defines_tests(workflow, target):
    """The stub case: the file is present, and holds nothing to run."""
    path = REPO / target
    if not path.exists():
        pytest.skip("covered by test_ci_target_exists")
    n = _test_count(path)
    assert n > 0, (
        f"{workflow} runs {target}, which defines no tests. If its content "
        f"moved elsewhere, point the workflow at the new location and delete "
        f"the stub — a green step over an empty file reports success it did "
        f"not earn."
    )


@pytest.mark.parametrize(
    "workflow,target",
    [(w, t) for w, t in _TARGETS if t.endswith("/")],
    ids=[f"{w}:{t}" for w, t in _TARGETS if t.endswith("/")],
)
def test_ci_target_dir_is_not_empty(workflow, target):
    path = REPO / target
    if not path.exists():
        pytest.skip("covered by test_ci_target_exists")
    files = [p for p in path.rglob("test_*.py")]
    assert files, f"{workflow} runs {target}, which contains no test modules"
    assert any(_test_count(p) > 0 for p in files), (
        f"{workflow} runs {target}; every module under it is empty of tests"
    )


class TestTheMergeGateCoversTheSuites:
    """gitea's ci.yml is the merge gate; GitHub's test.yml is advisory.

    The gates suites were only ever run by the advisory forge, so their
    breakage was invisible for months. Whatever the two forges disagree on,
    the merge gate must not be the weaker of the pair.
    """

    def _dirs(self, wf: Path) -> set[str]:
        return {t for t in _targets(wf) if t.endswith("/")}

    def test_gitea_runs_every_suite_directory_github_runs(self):
        gitea, github = _WORKFLOWS
        if not github.exists():  # pragma: no cover - github workflow optional
            pytest.skip("no github workflow to compare against")
        missing = self._dirs(github) - self._dirs(gitea)
        assert not missing, (
            f"the advisory forge runs suites the merge gate does not: "
            f"{sorted(missing)}. A suite only GitHub runs is a suite whose "
            f"failures block nothing — that is how olav-netops/tests/gates/ "
            f"stayed red."
        )
