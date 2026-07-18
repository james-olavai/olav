"""Wiring proof for the admin/reflector self-improvement agent.

Definition-of-Done: a feature must be reachable from a real entry point, not
just have passing unit tests. The reflector's real entry point is the daily
cron job → `olav --agent admin` → admin routes to reflector. This test proves
that chain is intact (cron schedule declared, agent routable, scripts callable)
AND that the anti-hallucination contract holds (the scan returns a BOUNDED
histogram, never raw log text).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SRC_ADMIN = REPO / "src/olav/data/workspace/admin"
REFLECTOR = SRC_ADMIN / "reflector"


def _load(script: str):
    path = REFLECTOR / "scripts" / f"{script}.py"
    spec = importlib.util.spec_from_file_location(f"_refl_{script}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. Entry point: the daily cron schedule exists and targets admin ──────
def test_reflect_cron_schedule_declared():
    """A `reflect` job must be in cron_schedules.yaml, routed to admin — this
    is the real entry point that fires the reflector daily."""
    cron_yaml = (
        REPO / ".olav/workspace/netops/netops_init/config/cron_schedules.yaml"
    )
    data = yaml.safe_load(cron_yaml.read_text())
    schedules = data.get("schedules", {})
    assert "reflect" in schedules, "no `reflect` cron schedule declared"
    job = schedules["reflect"]
    assert job.get("agent") == "admin", "reflect job must route to the admin agent"
    assert job.get("cron"), "reflect job needs a cron expression"
    # instruction must carry a keyword admin routes to reflector on
    assert "reflect" in job.get("instruction", "").lower()


# ── 2. Routability: admin declares reflector + routes to it ───────────────
def test_admin_declares_and_routes_reflector():
    skill = (SRC_ADMIN / "SKILL.md").read_text()
    fm = yaml.safe_load(skill.split("---", 2)[1])
    paths = [s["path"] for s in fm.get("subagents", [])]
    assert "./reflector/SKILL.md" in paths, "admin does not declare reflector as a sub-agent"
    # a routing rule must send reflect-intent to reflector
    assert 'task("reflector"' in skill, "admin has no routing rule to reflector"
    # route_keywords must mention reflection so the orchestrator can match
    kw = " ".join(fm.get("route_keywords", [])).lower()
    assert "reflect" in kw


# ── 3. Callability: reflector declares its scripts + the recipe ───────────
def test_reflector_scripts_declared_and_present():
    skill = (REFLECTOR / "SKILL.md").read_text()
    fm = yaml.safe_load(skill.split("---", 2)[1])
    declared = {s["name"]: s["file"] for s in fm.get("scripts", [])}
    expected = {
        "scan_error_signatures",
        "record_reflection",
        "propose_guide_draft",
        "draft_code_fix",
    }
    assert expected <= set(declared), f"missing script declarations: {expected - set(declared)}"
    for name, file in declared.items():
        assert (REFLECTOR / "scripts" / file).exists(), f"declared script {file} missing on disk"
    # execute_skill_script must be a tool, and the prompt must carry the
    # self-named recipe (the reachability class the DoD rule exists for)
    assert "execute_skill_script" in fm.get("tools", [])
    assert 'skill_name="reflector"' in skill


# ── 4. Anti-hallucination contract: scan is BOUNDED, never raw logs ───────
def test_scan_returns_bounded_histogram(tmp_path, monkeypatch):
    mod = _load("scan_error_signatures")

    # A signature must fold volatile tokens (ids/numbers/timestamps).
    s1 = mod._signature("2026-07-18 10:00:00 ERROR run abcd1234 failed after 5 retries")
    s2 = mod._signature("2026-07-18 11:30:59 ERROR run beef5678 failed after 9 retries")
    assert s1 == s2, "signatures must normalize ids/numbers/timestamps to group variants"

    # max_signatures caps the output regardless of how many distinct errors.
    # Use genuinely distinct messages (distinct WORDS, not a varying number —
    # a varying number correctly folds to ONE signature, which is the point).
    fake_logs = tmp_path / "logs"
    fake_logs.mkdir()
    words = [
        "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
        "hotel", "india", "juliet", "kilo", "lima",
    ]
    lines = "\n".join(f"ERROR the {w} subsystem crashed unexpectedly" for w in words)
    (fake_logs / "x.log").write_text(lines, encoding="utf-8")
    import olav.core.config as cfg
    monkeypatch.setattr(cfg, "LOGS_DIR", str(fake_logs))

    out = mod.scan_error_signatures(
        since_hours=1, max_signatures=5, scan_text_logs=True, db_path=str(tmp_path / "none.duckdb")
    )
    assert out["shown"] <= 5, "scan must respect max_signatures cap"
    assert out["distinct_signatures"] >= out["shown"]
    assert out["truncated"] is True, "must flag truncation when distinct > shown"
    # each example is a string, not a dumped file
    for sig in out["signatures"]:
        assert isinstance(sig["example"], str)
        assert sig["count"] >= 1


def test_tail_bytes_never_reads_whole_file(tmp_path):
    """The tail reader must cap bytes — the 229 MB api_server.log hazard."""
    mod = _load("scan_error_signatures")
    big = tmp_path / "big.log"
    big.write_text("HEADER-should-not-be-read\n" + ("x" * 5000 + "\n") * 100, encoding="utf-8")
    tail = mod._tail_bytes(big, max_bytes=1000)
    assert len(tail.encode("utf-8")) <= 1000
    assert "HEADER-should-not-be-read" not in tail  # only the tail is read


# ── 4b. reflection near-duplicate dedup (L2 gate) ─────────────────────────
def test_record_reflection_near_dup_helpers():
    """The near-dup dedup uses an L2 distance gate (0.3) so paraphrased/repeat
    reflections don't pile up (olav kb bench surfaced this: near-dups tank
    self-recall@1). Deterministic — no embedder/store needed."""
    mod = _load("record_reflection")

    assert mod.NEAR_DUP_L2 == 0.3
    # _l2 is plain euclidean distance
    assert mod._l2([0.0, 0.0], [3.0, 4.0]) == 5.0
    assert mod._l2([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0

    # _nearest_reflection_l2 reads the store's reported distance, +inf if none
    class _HitStore:
        def search_by_vector(self, *a, **k):
            return [{"score": 0.12}]

    class _EmptyStore:
        def search_by_vector(self, *a, **k):
            return []

    assert mod._nearest_reflection_l2(_HitStore(), [1.0], "memory") == 0.12
    assert mod._nearest_reflection_l2(_EmptyStore(), [1.0], "memory") == float("inf")


# ── 5. TIER_DEFAULTS carries the log-scan cap ─────────────────────────────
def test_tier_defaults_have_log_scan_cap():
    from olav.core.config import TIER_DEFAULTS

    for tier in ("small", "medium", "large"):
        assert "log_scan_max_signatures" in TIER_DEFAULTS[tier], (
            f"{tier} tier missing log_scan_max_signatures cap"
        )
    # small tier must be the tightest (bounded context for weak models)
    assert (
        TIER_DEFAULTS["small"]["log_scan_max_signatures"]
        <= TIER_DEFAULTS["medium"]["log_scan_max_signatures"]
        <= TIER_DEFAULTS["large"]["log_scan_max_signatures"]
    )
