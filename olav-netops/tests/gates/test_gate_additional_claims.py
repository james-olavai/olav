"""Gate Claim Verification Tests — Additional Claims

Covers claims that had no automated tests prior to this file.
All tests here are offline or use temporary DuckDB fixtures — no live devices required.

Claims covered:
  C-NE-01: /netops_init --dry-run passes environment checks (structural + subprocess)
  C-NE-03: /netops_init populates netops.parsed_outputs (DB gate — skipif no DB)
  C-NE-04: /netops_init generates topology links from LLDP/CDP (DB gate — skipif no DB)
  C-NE-16: Blacklisted commands rejected by execute_cli (code gate + unit gate with tmp DB)
  C-NE-24: execute_cli_parallel validates whitelist before execution (code gate + unit gate)
  C-NE-27: diff_sql_state compares any table between snapshots (unit gate with tmp DB)

NOTE: Claims requiring live SSH sessions (C-NE-06/12/14/17/18) are in test_claims_e2e.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

REPO_ROOT = Path(__file__).parents[2]        # olav-netops/
ROOT_REPO = REPO_ROOT.parent                  # /home/yhvh/Olav/ (monorepo root)
WORKSPACE = REPO_ROOT / ".olav/workspace"     # olav-netops vendored workspace copy
ROOT_WORKSPACE = ROOT_REPO / ".olav/workspace"  # authoritative runtime workspace
DB_PATH = REPO_ROOT / ".olav/databases/main.duckdb"

_DB_SKIP = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="main.duckdb not found — run /netops_init first",
)


# ---------------------------------------------------------------------------
# Fixtures — module loaders
# ---------------------------------------------------------------------------


# Where the validated-CLI code actually lives. Two moves happened and this
# file tracked neither: the agent directory is `netops/`, never `ops/`, and the
# rev ~282-299 migration moved these out of `tools/` into `scripts/`. Pointing
# at `ops/tools` meant every fixture below raised ModuleNotFoundError at setup,
# which is a collection ERROR rather than a skip — the gates job has been red
# since the migration, unnoticed because gitea's merge gate never ran it.
_SCRIPTS_DIR = WORKSPACE / "netops/scripts"


def _load_workspace_script(name: str):
    scripts_dir = str(_SCRIPTS_DIR)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import importlib
    return importlib.import_module(name)


@pytest.fixture(scope="module")
def execute_cli_mod():
    """C-NE-16's subject after `execute_cli` was retired.

    The module is gone, but the claim is not: `execute_cli_parallel` carries
    the same check, and says so in its own docstring ("Same whitelist/blacklist
    validation as the retired execute_cli"). Repointed rather than deleted —
    the product still rejects blacklisted commands, so the gate still has
    something to guard.
    """
    return _load_workspace_script("execute_cli_parallel")


@pytest.fixture(scope="module")
def execute_cli_parallel_mod():
    return _load_workspace_script("execute_cli_parallel")


@pytest.fixture(scope="module")
def diff_sql_mod():
    """C-NE-27's subject, now a package module rather than a workspace script.

    Chased by path twice already (ops/diff/tools → ops/analyze/tools → gone).
    The implementation settled in `olav_netops.core.diff.sql_state`, which is
    an ordinary import — no sys.path insertion, so the next reorganisation of
    the workspace cannot silently break this gate again.
    """
    from olav_netops.core.diff import sql_state

    return sql_state


# ---------------------------------------------------------------------------
# Fixtures — temporary DuckDB databases
# ---------------------------------------------------------------------------


@pytest.fixture
def commands_db(tmp_path):
    """Temporary DuckDB with a populated ``netops.commands`` table.

    Schema matches R73/R75 layout: ``(platform, command, safe_command,
    parser_type, parser_path, blacklisted, pipe_allowed, backup_only,
    synced_at)``.
    """
    db = tmp_path / "commands.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS netops")
        con.execute("""
            CREATE TABLE netops.commands (
                platform     VARCHAR NOT NULL,
                command      VARCHAR NOT NULL,
                safe_command VARCHAR NOT NULL,
                parser_type  VARCHAR,
                parser_path  VARCHAR,
                blacklisted  BOOLEAN NOT NULL,
                pipe_allowed BOOLEAN NOT NULL,
                backup_only  BOOLEAN NOT NULL,
                synced_at    TIMESTAMP
            )
        """)
        con.executemany(
            "INSERT INTO netops.commands VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            [
                ("cisco_ios", "write memory", "write_memory",
                 None, None, True, False, False),
                ("cisco_ios", "copy running-config startup-config",
                 "copy_running_config_startup_config",
                 None, None, True, False, False),
                ("cisco_ios", "debug ip ospf", "debug_ip_ospf",
                 None, None, True, False, False),
                ("cisco_ios", "show version", "show_version",
                 "ntc", "/p/show_version.textfsm", False, True, False),
                ("cisco_ios", "show ip route", "show_ip_route",
                 "ntc", "/p/show_ip_route.textfsm", False, True, False),
            ],
        )
    return db


@pytest.fixture
def two_snapshot_db(tmp_path):
    """Temporary DuckDB with two snapshots in netops.parsed_outputs.

    snap_1: (R1, show version) + (R1, show ip route)
    snap_2: (R1, show version) + (R1, show ip ospf)       ← show ip route missing, show ip ospf new
    """
    db = tmp_path / "snapshots.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE SCHEMA netops")
        con.execute("""
            CREATE TABLE netops.parsed_outputs (
                device_name VARCHAR,
                command VARCHAR,
                parsed_data JSON,
                snapshot_id VARCHAR,
                raw_output TEXT,
                raw_output_hash VARCHAR,
                ingested_at TIMESTAMP
            )
        """)
        con.executemany(
            "INSERT INTO netops.parsed_outputs "
            "(device_name, command, parsed_data, snapshot_id) VALUES (?, ?, ?, ?)",
            [
                ("R1", "show version",  '{"version":"15.5"}', "snap_20260226_100000"),
                ("R1", "show ip route", '{"prefix":"10.0.0.0/24"}', "snap_20260226_100000"),
                ("R1", "show version",  '{"version":"15.5"}', "snap_20260226_120000"),
                ("R1", "show ip ospf",  '{"neighbor":"10.0.0.2"}', "snap_20260226_120000"),
            ],
        )
    return db


# ---------------------------------------------------------------------------
# C-NE-01: /netops_init --dry-run passes environment checks
# ---------------------------------------------------------------------------


class TestNE01DryRunCheck:
    """C-NE-01: /netops_init --dry-run passes environment checks"""

    def test_dry_run_argument_in_source(self):
        """--dry-run flag is declared in netops_init/run.py."""
        run_py = ROOT_WORKSPACE / "netops/netops_init/run.py"
        if not run_py.exists():
            pytest.skip("netops_init/run.py not found")
        content = run_py.read_text()
        assert "--dry-run" in content, "--dry-run argument not found in run.py"
        assert "store_true" in content, "dry-run should be declared as action='store_true'"

    def test_dry_run_reports_the_environment_it_finds(self):
        """--dry-run must run the environment check and report its verdict.

        Asserted in both environments rather than skipped in one. This test
        previously demanded exit 0 unconditionally; it had been dead (pointed
        at `ops/netops_init/`, a path that has not existed since the agent
        directory was renamed) and un-skipping it turned CI red, because a
        plain `olav init` + `skill install` deploys only `hosts.yaml.example`.
        Exit 0 is a statement about the *runner's inventory*, not about the
        product.

        What C-NE-01 actually claims is that the check works. With an
        inventory that means a clean pass; without one it means a specific,
        actionable refusal. Both are verifiable, so neither environment needs
        a skip — and a silent skip is how this file rotted in the first place.
        """
        run_py = ROOT_WORKSPACE / "netops/netops_init/run.py"
        assert run_py.exists(), (
            f"{run_py} missing — skipping here would hide the whole claim"
        )
        result = subprocess.run(
            [sys.executable, str(run_py), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(ROOT_REPO),
            timeout=30,
        )
        combined = result.stdout + result.stderr
        assert "environment check" in combined.lower(), (
            f"--dry-run produced no environment-check report: {combined!r}"
        )

        inventory = ROOT_REPO / ".olav/config/nornir/hosts.yaml"
        if inventory.exists():
            assert result.returncode == 0, (
                f"inventory is present at {inventory}, so --dry-run should "
                f"pass; stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
            assert "dry-run" in combined.lower(), (
                f"Expected dry-run completion message, got: {combined!r}"
            )
        else:
            # The CI shape: the check must fail loudly and name what is
            # missing, not exit 0 on an unconfigured host.
            assert result.returncode != 0, (
                "no inventory present, yet --dry-run reported success — the "
                "environment check is not actually checking"
            )
            assert "hosts.yaml" in combined, (
                f"refusal must name the missing file so an operator can act; "
                f"got: {combined!r}"
            )


# ---------------------------------------------------------------------------
# C-NE-03: /netops_init populates netops.parsed_outputs
# ---------------------------------------------------------------------------


@_DB_SKIP
class TestNE03ParsedOutputsPopulated:
    """C-NE-03: /netops_init populates netops.parsed_outputs"""

    @pytest.fixture(autouse=True, scope="class")
    def db(self):
        self._con = duckdb.connect(str(DB_PATH), read_only=True)
        yield
        self._con.close()

    def test_parsed_outputs_has_rows(self):
        count = self._con.execute(
            "SELECT COUNT(*) FROM netops.parsed_outputs"
        ).fetchone()[0]
        assert count >= 1, f"netops.parsed_outputs should have rows, found {count}"

    def test_latest_snapshot_has_at_least_30_rows(self):
        """6 devices × 5+ commands per snapshot = at least 30 rows."""
        latest = self._con.execute(
            "SELECT MAX(snapshot_id) FROM netops.parsed_outputs"
        ).fetchone()[0]
        count = self._con.execute(
            "SELECT COUNT(*) FROM netops.parsed_outputs WHERE snapshot_id = ?",
            [latest],
        ).fetchone()[0]
        assert count >= 30, (
            f"Snapshot '{latest}' has {count} rows; "
            "expected ≥30 (6 devices × 5+ commands)"
        )


# ---------------------------------------------------------------------------
# C-NE-04: /netops_init generates topology links from LLDP/CDP
# ---------------------------------------------------------------------------


@_DB_SKIP
class TestNE04TopologyLinksGenerated:
    """C-NE-04: /netops_init generates topology links from LLDP/CDP"""

    @pytest.fixture(autouse=True, scope="class")
    def db(self):
        self._con = duckdb.connect(str(DB_PATH), read_only=True)
        yield
        self._con.close()

    def test_topology_links_has_rows(self):
        count = self._con.execute(
            "SELECT COUNT(*) FROM netops.topology_links"
        ).fetchone()[0]
        assert count >= 1, f"netops.topology_links should have rows, found {count}"

    def test_latest_snapshot_has_at_least_4_links(self):
        """A 6-node lab topology should have at least 4 bidirectional links."""
        latest = self._con.execute(
            "SELECT MAX(snapshot_id) FROM netops.topology_links"
        ).fetchone()[0]
        count = self._con.execute(
            "SELECT COUNT(*) FROM netops.topology_links WHERE snapshot_id = ?",
            [latest],
        ).fetchone()[0]
        assert count >= 4, (
            f"Snapshot '{latest}' has {count} topology links; expected ≥4"
        )


# ---------------------------------------------------------------------------
# C-NE-16: Blacklisted commands rejected by execute_cli
# ---------------------------------------------------------------------------


class TestNE16BlacklistedCommandsRejected:
    """C-NE-16: blacklisted commands are rejected before they reach a device.

    Originally asserted against `execute_cli`, which has since been retired.
    The claim outlived the module — `execute_cli_parallel` carries the same
    check — so the gate follows the behaviour rather than the filename.
    """

    def test_blacklist_check_code_present(self):
        """Code gate: the validated-CLI script still consults the blacklist."""
        path = _SCRIPTS_DIR / "execute_cli_parallel.py"
        assert path.exists(), (
            f"{path} missing — a skip here would hide the whole claim, which is "
            "how this file stayed broken through two directory moves"
        )
        content = path.read_text()
        assert "blacklisted" in content, f"blacklist check not found in {path.name}"
        # `execute_cli` signalled refusal with a "BLOCKED" marker string;
        # `execute_cli_parallel` returns a structured {"status": "blocked"}.
        # Assert the surviving contract, not the retired module's spelling —
        # keeping the old marker here would only re-break the gate.
        assert '"blocked"' in content or "'blocked'" in content, (
            f"{path.name} has no blocked-status path — a blacklisted command "
            "would fall through to execution"
        )
        assert "_validate_command" in content, (
            f"{path.name} never calls its own validator"
        )

    def test_blacklisted_yaml_has_destructive_commands(self):
        """Code gate: blacklisted_commands.yaml contains write/copy operations."""
        yaml_path = WORKSPACE / "netops/config/blacklisted_commands.yaml"
        if not yaml_path.exists():
            pytest.skip("blacklisted_commands.yaml not found")
        import yaml  # noqa: PLC0415
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data, "blacklisted_commands.yaml has no entries"
        cmds = [
            (e["command"] if isinstance(e, dict) else str(e)).lower()
            for e in data
        ]
        assert any("write" in c or "copy" in c for c in cmds), (
            f"Expected at least one destructive command (write/copy) in blacklist, got: {cmds}"
        )

    def test_validate_command_rejects_blacklisted(self, execute_cli_mod, commands_db):
        """Unit: _validate_command returns ok=False for a blacklisted command."""
        original = execute_cli_mod.MAIN_DB_PATH
        execute_cli_mod.MAIN_DB_PATH = commands_db
        try:
            result = execute_cli_mod._validate_command("write memory")
            assert result["ok"] is False, (
                f"'write memory' should be rejected; got: {result}"
            )
            assert "blacklisted" in result.get("reason", "").lower(), (
                f"Rejection reason should mention 'blacklisted'; got: {result.get('reason')!r}"
            )
        finally:
            execute_cli_mod.MAIN_DB_PATH = original

    def test_validate_command_allows_safe_command(self, execute_cli_mod, commands_db):
        """Unit: _validate_command returns ok=True for a safe, allowed command."""
        original = execute_cli_mod.MAIN_DB_PATH
        execute_cli_mod.MAIN_DB_PATH = commands_db
        try:
            result = execute_cli_mod._validate_command("show version")
            assert result["ok"] is True, (
                f"'show version' should be allowed; got: {result}"
            )
        finally:
            execute_cli_mod.MAIN_DB_PATH = original


# ---------------------------------------------------------------------------
# C-NE-24: execute_cli_parallel validates whitelist before execution
# ---------------------------------------------------------------------------


class TestNE24ExecuteCliParallelWhitelistValidation:
    """C-NE-24: execute_cli_parallel validates whitelist before execution"""

    def test_whitelist_validation_code_present(self):
        """Code gate: execute_cli_parallel.py calls _validate_command before SSH."""
        path = _SCRIPTS_DIR / "execute_cli_parallel.py"
        if not path.exists():
            pytest.skip("execute_cli_parallel.py not found")
        content = path.read_text()
        assert "_validate_command" in content, (
            "Command validation call not found in execute_cli_parallel.py"
        )
        assert "blacklisted" in content, (
            "Blacklist check not referenced in execute_cli_parallel.py"
        )

    def test_validate_command_rejects_blacklisted_parallel(
        self, execute_cli_parallel_mod, commands_db
    ):
        """Unit: execute_cli_parallel._validate_command rejects blacklisted commands."""
        original = execute_cli_parallel_mod.MAIN_DB_PATH
        execute_cli_parallel_mod.MAIN_DB_PATH = commands_db
        try:
            result = execute_cli_parallel_mod._validate_command("write memory")
            assert result["ok"] is False, (
                f"'write memory' should be rejected by execute_cli_parallel; got: {result}"
            )
        finally:
            execute_cli_parallel_mod.MAIN_DB_PATH = original

    def test_validate_command_allows_show_command_parallel(
        self, execute_cli_parallel_mod, commands_db
    ):
        """Unit: execute_cli_parallel._validate_command allows show commands."""
        original = execute_cli_parallel_mod.MAIN_DB_PATH
        execute_cli_parallel_mod.MAIN_DB_PATH = commands_db
        try:
            result = execute_cli_parallel_mod._validate_command("show ip route")
            assert result["ok"] is True, (
                f"'show ip route' should be allowed; got: {result}"
            )
        finally:
            execute_cli_parallel_mod.MAIN_DB_PATH = original


# ---------------------------------------------------------------------------
# C-NE-27: diff_sql_state compares any table between snapshots
# ---------------------------------------------------------------------------


class TestNE27DiffSqlStateComparesSnapshots:
    """C-NE-27: diff_sql_state compares any table between snapshots"""

    def test_diff_returns_expected_structure(self, diff_sql_mod, two_snapshot_db):
        """Unit: diff_sql_state result contains 'missing_in_t2' and 'new_in_t2' keys."""
        original = diff_sql_mod.MAIN_DB_PATH
        diff_sql_mod.MAIN_DB_PATH = two_snapshot_db
        try:
            result = diff_sql_mod.diff_sql_state(
                "netops.parsed_outputs",
                "snap_20260226_100000",
                "snap_20260226_120000",
            )
            assert "missing_in_t2" in result, (
                f"Expected 'missing_in_t2' key; got keys: {list(result.keys())}"
            )
            assert "new_in_t2" in result, (
                f"Expected 'new_in_t2' key; got keys: {list(result.keys())}"
            )
        finally:
            diff_sql_mod.MAIN_DB_PATH = original

    def test_diff_detects_missing_and_new_rows(self, diff_sql_mod, two_snapshot_db):
        """Unit: diff_sql_state identifies rows that disappeared and appeared between snapshots."""
        original = diff_sql_mod.MAIN_DB_PATH
        diff_sql_mod.MAIN_DB_PATH = two_snapshot_db
        try:
            result = diff_sql_mod.diff_sql_state(
                "netops.parsed_outputs",
                "snap_20260226_100000",
                "snap_20260226_120000",
            )
            missing = result.get("missing_in_t2", [])
            new = result.get("new_in_t2", [])
            # 'show ip route' was in snap_1 but not snap_2 → missing
            missing_cmds = [r.get("command") for r in missing]
            assert "show ip route" in missing_cmds, (
                f"Expected 'show ip route' as missing row; got missing: {missing_cmds}"
            )
            # 'show ip ospf' appeared in snap_2 but not snap_1 → new
            new_cmds = [r.get("command") for r in new]
            assert "show ip ospf" in new_cmds, (
                f"Expected 'show ip ospf' as new row; got new: {new_cmds}"
            )
        finally:
            diff_sql_mod.MAIN_DB_PATH = original

    def test_diff_same_snapshots_returns_empty_lists(self, diff_sql_mod, two_snapshot_db):
        """Unit: diffing the same snapshot against itself returns no changes."""
        original = diff_sql_mod.MAIN_DB_PATH
        diff_sql_mod.MAIN_DB_PATH = two_snapshot_db
        try:
            result = diff_sql_mod.diff_sql_state(
                "netops.parsed_outputs",
                "snap_20260226_100000",
                "snap_20260226_100000",
            )
            assert result.get("missing_in_t2", []) == [], (
                f"No rows should be missing when comparing same snapshot; got: {result}"
            )
            assert result.get("new_in_t2", []) == [], (
                f"No new rows should appear when comparing same snapshot; got: {result}"
            )
        finally:
            diff_sql_mod.MAIN_DB_PATH = original
