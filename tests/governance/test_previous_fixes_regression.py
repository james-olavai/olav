"""Regression guards for fixes landed in Sprint 1 rounds 1–4.

Each test asserts the *absence* of a specific anti-pattern that would
re-introduce a known defect. Kept as pure source/AST inspections so the
tests run without spinning up DBs or external services.

Covered:
  * CORE-02 — bare ``except Exception: pass`` floor in ``src/olav/core/``
  * CORE-03 — ``_backup_commands`` uses parameterised SQL
  * CORE-04 — ``tool_discovery.py`` does not insert into ``sys.path``
  * NETOPS-06 — ``_collect_cmd`` has no outer try wrapping ``target.run``
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from tests.governance._paths import NETOPS_INIT_DIR

REPO = Path(__file__).resolve().parents[2]


# ──────────────────────────────────────────────────────────────────────────
# CORE-02
# ──────────────────────────────────────────────────────────────────────────

# Known intentional idempotent DDL — documented in api_registry.py with the
# comment "# column already exists or DDL already added it". If you need to
# raise this floor, audit the new hit first.
# Current baseline after core memory/curator compatibility shims.
_CORE02_MAX_BARE_EXCEPT_PASS = 16


def _count_bare_except_pass(tree: ast.AST) -> int:
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # "except Exception:" with type=Name("Exception") — skip tuples like
        # "except (KeyError, ValueError):" and bare "except:".
        if not (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
            continue
        # Body must be exactly a single Pass statement.
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            n += 1
    return n


def test_core02_bare_except_pass_floor():
    total = 0
    for py in (REPO / "src" / "olav" / "core").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        total += _count_bare_except_pass(ast.parse(py.read_text(encoding="utf-8")))
    assert total <= _CORE02_MAX_BARE_EXCEPT_PASS, (
        f"Found {total} bare `except Exception: pass` swallows in src/olav/core/ "
        f"(floor is {_CORE02_MAX_BARE_EXCEPT_PASS}). Add a logger.debug(...) line "
        "or document the suppression inline."
    )


# ──────────────────────────────────────────────────────────────────────────
# CORE-03
# ──────────────────────────────────────────────────────────────────────────


def test_core03_backup_commands_uses_parameterised_sql():
    from olav.core.ingest_manager import IngestManager

    src = inspect.getsource(IngestManager._backup_commands)
    assert 'placeholders = ",".join(["?"] * len(backup_commands))' in src, (
        "_backup_commands no longer uses ? placeholders — CORE-03 regression. "
        "Reverting to f-string SQL concat opens an injection vector if YAML "
        "entries ever contain single quotes."
    )
    # Smoke-guard against the pre-fix idiom sneaking back in.
    assert "f\"'{c}'\"" not in src and "f\"'{cmd}'\"" not in src, (
        "Detected f-string SQL concat of command literals in _backup_commands."
    )


# ──────────────────────────────────────────────────────────────────────────
# CORE-04
# ──────────────────────────────────────────────────────────────────────────


def test_core04_tool_discovery_no_syspath_insert():
    src = (REPO / "src" / "olav" / "core" / "tool_discovery.py").read_text(encoding="utf-8")
    assert "sys.path.insert" not in src, (
        "tool_discovery.py re-introduced sys.path.insert — CORE-04 regression. "
        "Module-level sys.path mutation leaks across the whole process; prefer "
        "importlib.util.spec_from_file_location for per-file loads."
    )


# ──────────────────────────────────────────────────────────────────────────
# NETOPS-06
# ──────────────────────────────────────────────────────────────────────────


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_netops06_collect_cmd_no_outer_try_wrapping_target_run():
    run_py = NETOPS_INIT_DIR / "run.py"
    tree = ast.parse(run_py.read_text(encoding="utf-8"))
    fn = _find_function(tree, "_collect_cmd")
    assert fn is not None, "_collect_cmd missing from run.py"

    # NETOPS-06 regression: a `try:` at the top level of _collect_cmd body
    # catching everything around `target.run(...)` swallows per-host
    # successes when any single device errors. The fix removed that outer
    # wrapper — this assertion re-breaks the moment someone adds it back.
    for stmt in fn.body:
        if isinstance(stmt, (ast.Try, ast.TryStar)):
            # Inspect whether any handler catches base Exception — the smell
            # is the whole-run wrapper, not narrow Nornir-config catches.
            for handler in stmt.handlers:
                caught = handler.type
                is_broad = (
                    caught is None
                    or (isinstance(caught, ast.Name) and caught.id == "Exception")
                )
                if is_broad:
                    raise AssertionError(
                        "_collect_cmd has a top-level try/except Exception wrapping "
                        "its body — NETOPS-06 regression. Nornir already isolates "
                        "per-host failures via multi.failed; a broad outer try "
                        "marks every device as failed on any single error."
                    )
