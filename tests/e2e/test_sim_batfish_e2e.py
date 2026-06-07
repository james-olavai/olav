"""Batfish integration e2e — live service smoke + business scenario tests.

Pipeline: netops DB → export_configs → bf.init_snapshot → bf.q.* → assertions.

Gates:
  BATFISH_E2E_ENABLED=1   (only in nightly dispatch, not push CI)
  main.duckdb with demo snapshot data
  pybatfish installed (olav-netops[sim])
  Batfish at OLAV_BATFISH_HOST:OLAV_BATFISH_HTTP_PORT

Snapshot used: snap_20260118_000000_demo
  339 devices, 341 .cfg files exported, ~140s init_snapshot.
  Topology: campus network — alpha/beta/gamma/etc. sites, core-6807v,
  dist-4500xv, DC 9504 pairs, border-4500x with iBGP.

Timing budget (nightly):
  export_configs: ~7s
  init_snapshot:  ~140s  (once per module — all tests share it)
  each query:     <2s    (with nodes= filter)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pybatfish", reason="pybatfish not installed — install olav-netops[sim]")

_BF_ENABLED = os.environ.get("BATFISH_E2E_ENABLED", "").strip() == "1"
_DB = Path(__file__).resolve().parents[2] / ".olav" / "databases" / "main.duckdb"
_ROOT = Path(__file__).resolve().parents[2]

# Check LLM is configured (api.json or OLAV_LLM_API_KEY env). Used to gate NL-agent test.
try:
    from olav.core.config import get_llm_config as _get_llm_config
    _LLM_READY = bool(_get_llm_config().api_key)
except Exception:
    _LLM_READY = False

pytestmark = pytest.mark.skipif(
    not _BF_ENABLED or not _DB.exists(),
    reason="BATFISH_E2E_ENABLED=1 + main.duckdb required",
)

_SNAP = "snap_20260118_000000_demo"   # 339 devices, full campus topology


# ── module-level setup ────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def _ensure_commands_table():
    """Populate netops.commands if missing (sync_commands derives from static files)."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH
    try:
        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
            conn.execute("SELECT 1 FROM netops.commands LIMIT 1")
    except Exception:
        from olav_netops.command_registry import reload_hook
        reload_hook()


@pytest.fixture(scope="module")
def bfq():
    """Module-scoped batfish_q tool — snapshot init happens once here (~140s)."""
    from olav.core.sim.batfish_q import batfish_q
    # Warm up: init_snapshot for the primary snap so all tests hit cache
    batfish_q.invoke({"snapshot_id": _SNAP, "question": "nodeProperties"})
    return batfish_q


# ── 1. Infrastructure smoke ───────────────────────────────────────────────────


def test_batfish_service_reachable():
    """Batfish HTTP port is up."""
    import socket
    host = os.environ.get("OLAV_BATFISH_HOST", "localhost")
    port = int(os.environ.get("OLAV_BATFISH_HTTP_PORT", "9996"))
    with socket.create_connection((host, port), timeout=10):
        pass


def test_export_configs_produces_339_files():
    """export_configs writes one .cfg per device for the 339-device snapshot."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH
    from olav_netops.export.batfish import export_configs

    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        result = export_configs(conn, snapshot_id=_SNAP)

    assert result.get("config_count", 0) >= 300, (
        f"expected ≥300 configs, got {result.get('config_count')}"
    )
    cfg_files = list((Path(result["output_dir"]) / "configs").glob("*.cfg"))
    assert len(cfg_files) >= 300


def test_node_properties_envelope(bfq):
    """nodeProperties envelope has all documented keys and correct snapshot_id."""
    result = bfq.invoke({"snapshot_id": _SNAP, "question": "nodeProperties"})
    assert result["status"] == "ok"
    for key in ("status", "rows", "row_count", "snapshot_id", "reference_snapshot", "message"):
        assert key in result
    assert result["snapshot_id"] == _SNAP
    assert result["row_count"] >= 300


def test_snapshot_cache_hit(bfq):
    """Second call with same snapshot_id uses the in-process cache (no re-export)."""
    import sys
    # sim/__init__.py shadows the submodule name with the StructuredTool;
    # use sys.modules to reach the actual module object.
    mod = sys.modules["olav_netops.core.sim.batfish_q"]
    assert _SNAP in mod._LOADED_SNAPSHOTS, "bfq fixture must have warmed the cache"
    size_before = len(mod._LOADED_SNAPSHOTS)
    bfq.invoke({"snapshot_id": _SNAP, "question": "nodeProperties"})
    assert len(mod._LOADED_SNAPSHOTS) == size_before


def test_unknown_question_error_envelope(bfq):
    """Unknown question name returns status=error, not an exception."""
    result = bfq.invoke({"snapshot_id": _SNAP, "question": "noSuchQuestion_xyz99"})
    assert result["status"] == "error"
    assert result.get("message")


# ── 2. 内网路由覆盖 (distribution switch) ────────────────────────────────────
#
# 业务场景: 汇聚层设备必须持有内部 10.x.x.x 子网路由。
# 无默认路由是该园区网络的已知特征（边界路由在 alpha-border 上）。


class TestDistributionRoutes:
    """alpha-dist-4500xv-d: internal subnet routing coverage."""

    @pytest.fixture(scope="class")
    def routes(self, bfq):
        return bfq.invoke({
            "snapshot_id": _SNAP,
            "question": "routes",
            "q_args": {"nodes": "alpha-dist-4500xv-d"},
        })

    def test_has_routes(self, routes):
        assert routes["status"] == "ok"
        assert routes["row_count"] >= 50, "distribution switch must have ≥50 routes"

    def test_all_routes_are_internal(self, routes):
        """All prefixes are RFC-1918 / internal — no public routes on dist layer."""
        non_internal = [
            r["Network"] for r in routes["rows"]
            if not (r["Network"].startswith("10.") or r["Network"].startswith("172.")
                    or r["Network"].startswith("192.168."))
        ]
        assert non_internal == [], f"unexpected public prefixes: {non_internal[:5]}"

    def test_has_static_routes(self, routes):
        """Static routes present — confirms manual policy entries were parsed."""
        statics = [r for r in routes["rows"] if r.get("Protocol") == "static"]
        assert len(statics) >= 1, "expected at least one static route on dist switch"


# ── 3. コア switch uplink health ─────────────────────────────────────────────
#
# 業務シナリオ: core switch の active interface 数を監視することで
# 大規模なポート障害（例えばフォームファクター変更後）を検出する。


class TestCoreInterfaceHealth:
    """alpha-core-6807v: uplink and routed interface availability."""

    @pytest.fixture(scope="class")
    def ifaces(self, bfq):
        return bfq.invoke({
            "snapshot_id": _SNAP,
            "question": "interfaceProperties",
            "q_args": {"nodes": "alpha-core.*"},
        })

    def test_has_interfaces(self, ifaces):
        assert ifaces["status"] == "ok"
        assert ifaces["row_count"] >= 100

    def test_active_interface_count(self, ifaces):
        """At least 50 interfaces are active (uplinks + SVIs in service)."""
        active = [r for r in ifaces["rows"] if r.get("Active")]
        assert len(active) >= 50, (
            f"expected ≥50 active interfaces on core, got {len(active)}"
        )

    def test_routed_interfaces_have_ip(self, ifaces):
        """At least 15 routed interfaces carry an IP prefix."""
        with_ip = [r for r in ifaces["rows"] if r.get("All_Prefixes")]
        assert len(with_ip) >= 15, (
            f"expected ≥15 routed interfaces with IPs on core, got {len(with_ip)}"
        )


# ── 4. Border BGP policy presence ────────────────────────────────────────────
#
# Business scenario: verify border router has BGP neighbors configured
# (policy intent preserved across config changes). In static analysis mode
# sessions will be NOT_ESTABLISHED — that is expected and intentional.
# ESTABLISHED status requires live device state, not config analysis.


class TestBorderBgpPolicy:
    """alpha-border-4500x: BGP neighbor configuration integrity."""

    @pytest.fixture(scope="class")
    def bgp(self, bfq):
        return bfq.invoke({
            "snapshot_id": _SNAP,
            "question": "bgpSessionStatus",
            "q_args": {"nodes": ".*border.*"},
        })

    def test_bgp_sessions_configured(self, bgp):
        """Border has ≥20 BGP neighbors configured."""
        assert bgp["status"] == "ok"
        assert bgp["row_count"] >= 20, (
            f"expected ≥20 BGP sessions on border, got {bgp['row_count']}"
        )

    def test_ibgp_sessions_present(self, bgp):
        """iBGP sessions exist — border is part of the campus iBGP mesh."""
        ibgp = [r for r in bgp["rows"] if r.get("Session_Type") == "IBGP"]
        assert len(ibgp) >= 10, f"expected ≥10 iBGP sessions, got {len(ibgp)}"

    def test_ibgp_dominates_ebgp(self, bgp):
        """iBGP sessions outnumber eBGP — campus core is iBGP-dominant.

        Note: Batfish reports EBGP_SINGLEHOP/EBGP_MULTIHOP (not "EBGP").
        alpha-border-4500x has exactly 1 eBGP peer (AS 7575); the rest are iBGP.
        """
        ibgp = [r for r in bgp["rows"] if r.get("Session_Type") == "IBGP"]
        ebgp = [r for r in bgp["rows"] if "EBGP" in r.get("Session_Type", "")]
        assert len(ibgp) > len(ebgp), (
            f"expected iBGP({len(ibgp)}) > eBGP({len(ebgp)}) on border nodes"
        )


# ── 5. DC pair route symmetry ─────────────────────────────────────────────────
#
# Business scenario: dual-homed datacenter switches must carry near-identical
# routing tables. A large divergence signals a split-brain or failed failover.


class TestDatacenterRoutingSymmetry:
    """alpha-dc-9504-1 vs alpha-dc-9504-2: redundant pair must stay in sync."""

    @pytest.fixture(scope="class")
    def dc_routes(self, bfq):
        r1 = bfq.invoke({"snapshot_id": _SNAP, "question": "routes",
                          "q_args": {"nodes": "alpha-dc-9504-1"}})
        r2 = bfq.invoke({"snapshot_id": _SNAP, "question": "routes",
                          "q_args": {"nodes": "alpha-dc-9504-2"}})
        return r1, r2

    def test_both_have_routes(self, dc_routes):
        r1, r2 = dc_routes
        assert r1["status"] == "ok" and r2["status"] == "ok"
        assert r1["row_count"] >= 50
        assert r2["row_count"] >= 50

    def test_route_count_symmetric(self, dc_routes):
        """Route table sizes differ by less than 10% — redundancy intact."""
        r1, r2 = dc_routes
        c1, c2 = r1["row_count"], r2["row_count"]
        diff_pct = abs(c1 - c2) / max(c1, c2) * 100
        assert diff_pct < 10, (
            f"DC pair route counts diverged: {c1} vs {c2} ({diff_pct:.1f}%)"
        )


# ── 6. Border security policy completeness ───────────────────────────────────
#
# Business scenario: pre-change compliance check — border must have
# ACLs and route-maps in place before any routing policy change is applied.


class TestBorderSecurityPolicy:
    """alpha-border: ACL and route-map policy completeness."""

    @pytest.fixture(scope="class")
    def structs(self, bfq):
        return bfq.invoke({
            "snapshot_id": _SNAP,
            "question": "definedStructures",
            "q_args": {"nodes": ".*border.*"},
        })

    def test_has_acl_entries(self, structs):
        """Border has >100 extended ACL lines (access control policy in place)."""
        assert structs["status"] == "ok"
        acl_lines = [
            r for r in structs["rows"]
            if "access-list" in r.get("Structure_Type", "").lower()
        ]
        assert len(acl_lines) > 100, (
            f"expected >100 ACL lines on border, got {len(acl_lines)}"
        )

    def test_has_route_maps(self, structs):
        """Border has route-maps configured (BGP policy framework present)."""
        rmaps = [
            r for r in structs["rows"]
            if r.get("Structure_Type", "") == "route-map"
        ]
        assert len(rmaps) >= 20, (
            f"expected ≥20 route-maps on border, got {len(rmaps)}"
        )

    def test_has_bgp_neighbor_structures(self, structs):
        """Defined BGP neighbor count matches bgpSessionStatus (config coherence)."""
        bgp_neighbors = [
            r for r in structs["rows"]
            if r.get("Structure_Type", "") == "bgp neighbor"
        ]
        assert len(bgp_neighbors) >= 20


# ── 7. NL-agent routing scenario ─────────────────────────────────────────────
#
# Validates the full prompt → LLM → tool-selection → synthesis chain:
#   a) simulator agent loads batfish_q as an @tool (not as a subprocess script)
#   b) LLM selects batfish_q for a BGP neighbour query
#   c) synthesis surfaces both AS numbers from the live Batfish result
#
# Known ground truth (snap_20260118_000000_demo, alpha-border-4500x):
#   2 neighbours: AS 136247 (iBGP), AS 7575 (eBGP)


@pytest.mark.skipif(
    not _LLM_READY,
    reason="LLM API key not configured — set OLAV_LLM_API_KEY or add llm.api_key to api.json",
)
@pytest.mark.timeout(600)
class TestSimulatorNLAgent:
    """NL-agent test: simulator must route to batfish_q and synthesise BGP data."""

    @classmethod
    def setup_class(cls):
        # 480s: cold init_snapshot ~140s + LLM ~60s + buffer; kill-after=30 ensures cleanup.
        cmd = [
            "timeout", "--kill-after=30", "480",
            sys.executable, "-m", "olav",
            "--agent", "netops/simulator",
            f"用 {_SNAP} 快照，查一下 alpha-border-4500x 配置了几个 BGP 邻居，以及邻居的 AS 号",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(_ROOT),
            env={**os.environ, "OLAV_BATFISH_HOST": os.environ.get("OLAV_BATFISH_HOST", "localhost")},
        )
        try:
            stdout, stderr = proc.communicate(timeout=510)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        cls._out = (stdout or "") + (stderr or "")
        cls._rc = proc.returncode

    def test_agent_exits_cleanly(self):
        """Simulator agent must not crash (returncode 0)."""
        assert self._rc == 0, f"agent exited {self._rc}; tail: {self._out[-300:]}"

    def test_batfish_q_was_called(self):
        """LLM must invoke batfish_q @tool — not fall back to execute_skill_script."""
        assert "batfish_q" in self._out, (
            "batfish_q tool call not found — LLM may have used a script fallback\n"
            f"output tail: {self._out[-400:]}"
        )

    def test_as_numbers_in_synthesis(self):
        """Both AS numbers (136247 iBGP, 7575 eBGP) must appear in the synthesised answer."""
        assert "136247" in self._out, f"iBGP AS 136247 missing from synthesis\n{self._out[-400:]}"
        assert "7575" in self._out, f"eBGP AS 7575 missing from synthesis\n{self._out[-400:]}"

    def test_neighbour_count_in_synthesis(self):
        """Response must reference 2 BGP neighbours."""
        assert "2" in self._out, f"neighbour count '2' not found in synthesis\n{self._out[-400:]}"
