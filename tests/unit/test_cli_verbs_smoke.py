"""
tests/unit/test_cli_verbs_smoke.py
──────────────────────────────────
P7 cycle 5 — minimal smoke tests for CLI verbs with low prior
coverage (from the audit in dev_docs/50 §12.2 / §11.1).  Each
verb gets a single sanity test: the module imports, the command
class instantiates, and ``--help`` or empty-args returns without
crashing.

This does NOT aim for full functional coverage of each verb — that's
a separate task for feature-by-feature audits.  It DOES guard against
the regression class where a shared helper rename breaks the import
graph for a rarely-invoked verb (catalog/explain/kb/reset/config are
the usual suspects).

Verbs covered here:
  * kb             olav.cli.commands.kb
  * catalog        olav.cli.commands.catalog
  * explain        olav.cli.commands.explain
  * refresh        olav.cli.commands.refresh
  * sessions       olav.cli.commands.sessions (recently refactored)
  * reset          (lives in main.py dispatcher; tested via subprocess)
  * config         olav.cli.commands.config_evolve
  * diff           olav.cli.commands.diff
  * trace-review   olav.cli.commands.trace_review
  * migrate        olav.cli.commands.migrate (P1 verb; sanity double-check)
  * init           olav.cli.commands.init
  * doctor         olav.cli.commands.doctor (dev_docs/99 §3.1)
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys

import pytest


# ── Test 1: every module imports cleanly ────────────────────────────────────


@pytest.mark.parametrize(
    "module_name",
    [
        "olav.cli.commands.kb",
        "olav.cli.commands.catalog",
        "olav.cli.commands.explain",
        "olav.cli.commands.refresh",
        "olav.cli.commands.sessions",
        "olav.cli.commands.config_evolve",
        "olav.cli.commands.diff",
        "olav.cli.commands.trace_review",
        "olav.cli.commands.migrate",
        "olav.cli.commands.init",
        "olav.cli.commands.doctor",
    ],
)
def test_command_module_imports(module_name: str) -> None:
    """The module must import without running into broken references,
    circular imports, or missing shared helpers."""
    importlib.import_module(module_name)


# ── Test 2: primary command class instantiates ─────────────────────────────


@pytest.mark.parametrize(
    "module_name,class_name",
    [
        ("olav.cli.commands.kb", "KbCommand"),
        ("olav.cli.commands.catalog", "CatalogCommand"),
        ("olav.cli.commands.explain", "ExplainCommand"),
        ("olav.cli.commands.refresh", "RefreshCommand"),
        ("olav.cli.commands.migrate", "MigrateCommand"),
        ("olav.cli.commands.doctor", "DoctorCommand"),
    ],
)
def test_command_class_instantiates(module_name: str, class_name: str) -> None:
    """Construct the main command class — catches __init__ regressions
    (missing config files, broken inheritance, etc.)."""
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)
    if cls is None:
        pytest.skip(f"{class_name} not found in {module_name}")
    instance = cls()
    assert instance is not None


# ── Test 3: `olav <verb> --help` subprocess smoke ──────────────────────────


_HELP_SMOKE_VERBS = [
    "migrate",
    "agent",
    "admin",
    "init",
    "list",
    "sessions",
    "workspace",
    "registry",
    "service",
    "kb",
    "catalog",
    "explain",
    "diff",
    "log",
    "refresh",
    "reset",
    "export",
    "config",
    "doctor",
]


@pytest.mark.parametrize("verb", _HELP_SMOKE_VERBS)
def test_verb_help_does_not_crash(verb: str) -> None:
    """``olav <verb> --help`` must return in <10s without a Python
    traceback.

    Uses subprocess so the test mirrors what users see and catches
    packaging / entry-point issues.  Skipped if the ``olav`` binary
    isn't findable — keeps the suite runnable from isolated envs.
    """
    olav_bin = shutil.which("olav")
    if not olav_bin:
        from pathlib import Path

        candidate = Path(sys.executable).parent / "olav"
        if candidate.is_file():
            olav_bin = str(candidate)
    if not olav_bin:
        pytest.skip("olav binary not on PATH and not next to sys.executable")

    result = subprocess.run(
        [olav_bin, verb, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    # Exit code != 0 is acceptable (some verbs don't register --help,
    # some print usage and exit 2).  Only fail if we see a Python
    # traceback leaking through — that's an actual regression.
    assert "Traceback" not in result.stderr, (
        f"olav {verb} --help crashed with traceback:\n{result.stderr}"
    )
    assert "Traceback" not in result.stdout, (
        f"olav {verb} --help crashed with traceback:\n{result.stdout}"
    )


# ── Test 4: `olav list` actually lists something ──────────────────────────


def test_olav_list_runs_without_crash() -> None:
    olav_bin = shutil.which("olav")
    if not olav_bin:
        from pathlib import Path

        candidate = Path(sys.executable).parent / "olav"
        if candidate.is_file():
            olav_bin = str(candidate)
    if not olav_bin:
        pytest.skip("olav binary not on PATH")

    result = subprocess.run(
        [olav_bin, "list"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "Traceback" not in result.stderr
    # Output either lists agents or says "No agents found"; both are ok.
    # Just assert the process exited normally.
    assert result.returncode == 0


# ── Test 5: `olav --help` top-level still works ───────────────────────────


def test_olav_top_level_help() -> None:
    olav_bin = shutil.which("olav")
    if not olav_bin:
        from pathlib import Path

        candidate = Path(sys.executable).parent / "olav"
        if candidate.is_file():
            olav_bin = str(candidate)
    if not olav_bin:
        pytest.skip("olav binary not on PATH")

    result = subprocess.run(
        [olav_bin, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    # Spot-check some known verbs are listed (protects the _KNOWN_COMMANDS
    # → subparsers wiring from silent drift).
    for verb in ("agent", "migrate", "admin", "kb"):
        assert verb in result.stdout, f"'olav {verb}' should appear in --help"
    # Removed verb must NOT appear (plural 'skills' still does — that's
    # a different verb).
    lines_with_skill_standalone = [
        ln
        for ln in result.stdout.splitlines()
        if "skill" in ln and "skills" not in ln
    ]
    # No bare "skill" references in the subcommand choices line.
    for ln in lines_with_skill_standalone:
        if "{" in ln:  # the choices block
            pytest.fail(f"bare 'skill' verb still in --help: {ln!r}")
