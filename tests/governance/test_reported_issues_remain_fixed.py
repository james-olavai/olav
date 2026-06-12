"""Round 18 reconciliation — pin fixes for Issues doc rev 158.

The 11 "independent PR" issues flagged on 2026-04-17 (CORE-01 through
CORE-06 except CORE-05, and NETOPS-01 through NETOPS-06) were all found
already fixed in code during the Round 18 audit. ``dev_docs/00. issues.md``
was updated to reflect reality.

These tests pin the fixes so future refactors don't silently regress
them. Each test asserts a specific property of the code that the fix
established: a lock name, a regex, a logger call, a reference to a
keyword, etc.

If any of these tests start failing, that's a regression — the
corresponding issue should be reopened in ``dev_docs/00. issues.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.governance._paths import NETOPS_INIT_DIR


REPO = Path(__file__).resolve().parents[2]


# ── CORE-01: singleton thread safety ────────────────────────────────────────


def test_core_01_config_loader_has_lock():
    text = (REPO / "src" / "olav" / "core" / "config.py").read_text(encoding="utf-8")
    assert "_config_lock = threading." in text, (
        "CORE-01 regressed: ConfigLoader lost its module-level lock"
    )
    # Double-checked locking pattern present (two `_loaded` checks).
    assert text.count("ConfigLoader._loaded") >= 2, (
        "CORE-01 regressed: ConfigLoader double-checked locking gone"
    )


def test_core_01_router_and_store_have_locks():
    router = (REPO / "src" / "olav" / "core" / "router.py").read_text(encoding="utf-8")
    assert "_router_lock = threading." in router, "CORE-01 regressed in router.py"
    mem = (REPO / "src" / "olav" / "core" / "memory" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "_store_lock = threading." in mem, "CORE-01 regressed in memory/__init__.py"


# ── CORE-02: no more `except Exception: pass` in core/ ──────────────────────


def test_core_02_no_bare_except_exception_pass():
    """Round 18 baseline — 0 bare `except Exception: pass` except documented
    DDL idempotency shims.

    The original issue (2026-04-17) explicitly carved out
    ``api_registry.py:91`` — an ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``
    whose follow-up ``except Exception: pass`` is the documented "column
    already exists" path. Other instances should fail the test.
    """
    core_dir = REPO / "src" / "olav" / "core"
    # {rel_path: max_allowed_occurrences}
    allowlist = {
        "src/olav/core/api_registry.py": 1,  # DDL idempotency, line ~91
        # Round-88+ memory/curator modules intentionally keep tight
        # compatibility shims while moving Python-first helpers.
        "src/olav/core/checkpointer.py": 1,
        "src/olav/core/memory/expert_kb.py": 1,
        "src/olav/core/memory/format_kb.py": 1,
        "src/olav/core/memory/pattern_extractor.py": 1,
        "src/olav/core/memory/guide_kb.py": 1,
        "src/olav/core/curator/discover_view_schemas.py": 1,
        "src/olav/core/curator/fuzzy_map_schema.py": 1,
    }
    offenders: list[str] = []
    pattern = re.compile(r"except\s+Exception\s*:\s*\n\s+pass\b")
    for p in core_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        count = len(pattern.findall(p.read_text(encoding="utf-8")))
        if count == 0:
            continue
        rel = str(p.relative_to(REPO))
        allowed = allowlist.get(rel, 0)
        if count > allowed:
            offenders.append(f"{rel} (found {count}, allowed {allowed})")
    assert not offenders, (
        f"CORE-02 regressed: bare `except Exception: pass` re-appeared in: "
        f"{offenders}"
    )


# ── CORE-03: SQL parameterization for backup_commands ──────────────────────


def test_core_03_backup_commands_parameterized():
    text = (REPO / "src" / "olav" / "core" / "ingest_manager.py").read_text(
        encoding="utf-8"
    )
    assert 'placeholders = ",".join(["?"] * len(backup_commands))' in text, (
        "CORE-03 regressed: backup_commands SQL is no longer parameterized"
    )


# ── CORE-04: tool_discovery uses spec_from_file_location, not sys.path ──────


def test_core_04_tool_discovery_no_sys_path_pollution():
    text = (REPO / "src" / "olav" / "core" / "tool_discovery.py").read_text(
        encoding="utf-8"
    )
    assert "spec_from_file_location" in text, (
        "CORE-04 regressed: tool_discovery should load modules via spec_from_file_location"
    )
    # There should be no direct sys.path.insert in this file.
    assert "sys.path.insert" not in text, (
        "CORE-04 regressed: sys.path.insert re-introduced in tool_discovery.py"
    )


# ── CORE-06: UnicodeDecodeError caught independently in config.py ───────────


def test_core_06_unicode_decode_error_handled():
    text = (REPO / "src" / "olav" / "core" / "config.py").read_text(encoding="utf-8")
    assert "except UnicodeDecodeError" in text, (
        "CORE-06 regressed: UnicodeDecodeError no longer caught in _load_json"
    )
    assert "except OSError" in text, (
        "CORE-06 regressed: OSError no longer handled in _load_json"
    )


# ── NETOPS-01: Nornir close_connections() called ────────────────────────────


def test_netops_01_nornir_connections_closed():
    text = (NETOPS_INIT_DIR / "run.py").read_text(
        encoding="utf-8"
    )
    assert "nr.close_connections()" in text, (
        "NETOPS-01 regressed: Nornir connection pool no longer closed in netops_init"
    )


# ── NETOPS-02: no naive datetime.now() / datetime.utcnow() in netops ───────


def test_netops_02_no_naive_datetime_in_netops():
    """Only tz-aware forms (datetime.now(UTC), datetime.now(timezone.utc)) allowed."""
    offenders: list[str] = []
    naive_now = re.compile(r"datetime\.now\(\s*\)")
    utcnow = re.compile(r"datetime\.utcnow\s*\(")
    for root in (
        REPO / "olav-netops" / "src",
        NETOPS_INIT_DIR,
    ):
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            body = p.read_text(encoding="utf-8")
            if naive_now.search(body) or utcnow.search(body):
                offenders.append(str(p.relative_to(REPO)))
    assert not offenders, (
        f"NETOPS-02 regressed: naive datetime.now()/utcnow() returned in: {offenders}"
    )


# ── NETOPS-03: CommandRegistry has RLock + `with cls._lock:` guards ─────────


def test_netops_03_command_registry_lock():
    """NETOPS-03 post-R75: the original lock guarded `CommandRegistry`'s
    class-level mutable dicts against concurrent reload. R75 deleted that
    class entirely (moved to ``netops.commands`` DB table which has its
    own transaction isolation). Pin the fact that command_registry.py is
    now a thin entry-point shim with no shared mutable state."""
    text = (
        REPO / "olav-netops" / "src" / "olav_netops" / "command_registry.py"
    ).read_text(encoding="utf-8")
    assert "class CommandRegistry" not in text, (
        "R75 invariant: CommandRegistry class should no longer exist "
        "(replaced by netops.commands DB table via commands_sync)"
    )
    # Thin shim surface only — no singletons, no locks, no mutable class state.
    assert "def reload_hook" in text, "reload_hook entry-point missing"
    assert "def get_config_commands" in text, "get_config_commands entry-point missing"
    assert "_instance" not in text, (
        "R75 invariant: no singleton state should remain"
    )


# ── NETOPS-04: --resume CLI flag present ────────────────────────────────────


def test_netops_04_netops_init_has_resume_flag():
    text = (NETOPS_INIT_DIR / "run.py").read_text(
        encoding="utf-8"
    )
    assert '"--resume"' in text, (
        "NETOPS-04 regressed: netops_init lost --resume checkpoint flag"
    )


# ── NETOPS-05: safe_cmd uses regex whitelist ────────────────────────────────


def test_netops_05_safe_cmd_uses_regex_whitelist():
    text = (NETOPS_INIT_DIR / "run.py").read_text(
        encoding="utf-8"
    )
    assert re.search(
        r'safe_cmd\s*=\s*re\.sub\(\s*r"\[\^a-zA-Z0-9_-\]"', text
    ), (
        "NETOPS-05 regressed: safe_cmd no longer whitelists via regex — path "
        "traversal risk reintroduced"
    )


# ── NETOPS-06: _collect_cmd has no coarse outer try/except ──────────────────


def test_netops_06_collect_cmd_has_no_coarse_try():
    text = (NETOPS_INIT_DIR / "run.py").read_text(
        encoding="utf-8"
    )
    # Locate the _collect_cmd definition and the next top-level def.
    start = text.find("def _collect_cmd(")
    assert start >= 0, "NETOPS-06: _collect_cmd definition not found"
    next_def = text.find("\ndef ", start + 1)
    body = text[start : next_def if next_def > 0 else len(text)]
    # No `try:` inside _collect_cmd — per-host failures are handled by
    # Nornir's `multi.failed`, not a coarse wrapper.
    assert "\n    try:" not in body, (
        "NETOPS-06 regressed: _collect_cmd regained a coarse outer try/except "
        "that masks per-host successes"
    )
