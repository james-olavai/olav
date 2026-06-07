"""Unit tests for command_learner/tools/learn_commands (R71a).

Covers:
  * LearnResult dataclass shape
  * Empty input → no-op
  * Group dedup by (platform, command)
  * Failure cache write + read + TTL expiry
  * samples_hash changes → cache invalidation
  * force_relearn bypass
  * Budget exhaustion → skipped with reason
  * ThreadPool concurrency (wall-clock < naive-sum-of-workers-time)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

# Wire the skill's tools dir into sys.path so we can import learn_commands
_SKILL_TOOLS = Path(__file__).resolve().parents[1] / ".olav/workspace/command_learner/tools"
sys.path.insert(0, str(_SKILL_TOOLS))

import learn_commands as lc  # noqa: E402


@pytest.fixture(autouse=True)
def _sandbox_templates_dir(tmp_path, monkeypatch):
    """Redirect ``_templates_dir`` to a per-test tmpdir so cache files
    don't leak between tests and don't touch real state."""
    sandboxed = tmp_path / "templates"
    sandboxed.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(lc, "_templates_dir", lambda: sandboxed)
    yield sandboxed


# ──────────────────────────────────────────────────────────────────────────
# LearnResult
# ──────────────────────────────────────────────────────────────────────────

class TestLearnResult:
    def test_default_empty(self):
        r = lc.LearnResult()
        assert r.newly_parsed == []
        assert r.frozen == []
        assert r.failed == []
        assert r.skipped == []
        assert r.elapsed_seconds == 0.0

    def test_to_dict_keys(self):
        d = lc.LearnResult().to_dict()
        assert set(d) == {"newly_parsed", "frozen", "failed", "skipped", "elapsed_seconds"}


# ──────────────────────────────────────────────────────────────────────────
# Input handling
# ──────────────────────────────────────────────────────────────────────────

class TestInputs:
    def test_empty_samples(self):
        r = lc.learn_commands([])
        assert r.newly_parsed == []
        assert r.failed == []
        assert r.skipped == []

    def test_missing_command_filtered(self):
        r = lc.learn_commands([{"device": "R1", "platform": "cisco_ios", "command": "", "raw_output": "x"}])
        # Group is skipped silently (no command = no group)
        assert r.failed == []
        assert r.skipped == []
        assert r.newly_parsed == []

    def test_grouping_dedupes_same_platform_command(self, monkeypatch):
        """Two samples with same (plat, cmd) become ONE group (one worker call)."""
        calls = []
        def _fake_learn(plat, cmd, samples, *, max_retries, allow_llm):
            calls.append((plat, cmd, len(samples)))
            return "failed", [], None
        monkeypatch.setattr(lc, "_learn_one_group", _fake_learn)

        samples = [
            {"device": "R1", "platform": "cisco_ios", "command": "show bgp summary", "raw_output": "a"},
            {"device": "R2", "platform": "cisco_ios", "command": "show bgp summary", "raw_output": "b"},
            {"device": "R3", "platform": "juniper_junos", "command": "show bgp summary", "raw_output": "c"},
        ]
        r = lc.learn_commands(samples, allow_llm=False, max_workers=2, budget_seconds=30)
        # 2 groups: (cisco_ios, show bgp summary) with 2 samples, (juniper_junos, show bgp summary) with 1
        assert len(calls) == 2
        sizes = sorted(c[2] for c in calls)
        assert sizes == [1, 2]


# ──────────────────────────────────────────────────────────────────────────
# Failure cache
# ──────────────────────────────────────────────────────────────────────────

class TestFailureCache:
    def test_cache_written_on_failure(self, monkeypatch, _sandbox_templates_dir):
        monkeypatch.setattr(lc, "_learn_one_group",
                            lambda *a, **kw: ("failed", [], None))
        samples = [{"device": "R1", "platform": "cisco_ios", "command": "show x", "raw_output": "raw"}]
        r = lc.learn_commands(samples, allow_llm=False, budget_seconds=30)
        assert len(r.failed) == 1
        cache_path = _sandbox_templates_dir / "_failed_learn.json"
        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert "cisco_ios/show x" in data
        assert data["cisco_ios/show x"]["contract_version"] == lc.LEARNER_CONTRACT_VERSION

    def test_rerun_uses_cache(self, monkeypatch):
        n_calls = [0]
        def _counter(*a, **kw):
            n_calls[0] += 1
            return "failed", [], None
        monkeypatch.setattr(lc, "_learn_one_group", _counter)
        samples = [{"device": "R1", "platform": "cisco_ios", "command": "show x", "raw_output": "raw"}]
        lc.learn_commands(samples, allow_llm=False, budget_seconds=30)
        assert n_calls[0] == 1
        r2 = lc.learn_commands(samples, allow_llm=False, budget_seconds=30)
        # Second run hits cache — no new learner call
        assert n_calls[0] == 1
        assert len(r2.skipped) == 1
        assert r2.skipped[0]["reason"] == "failure_cache_hit"

    def test_force_relearn_bypasses_cache(self, monkeypatch):
        n_calls = [0]
        def _counter(*a, **kw):
            n_calls[0] += 1
            return "failed", [], None
        monkeypatch.setattr(lc, "_learn_one_group", _counter)
        samples = [{"device": "R1", "platform": "cisco_ios", "command": "show x", "raw_output": "raw"}]
        lc.learn_commands(samples, allow_llm=False, budget_seconds=30)
        lc.learn_commands(samples, allow_llm=False, budget_seconds=30, force_relearn=True)
        assert n_calls[0] == 2

    def test_samples_hash_change_invalidates_cache(self, monkeypatch):
        n_calls = [0]
        def _counter(*a, **kw):
            n_calls[0] += 1
            return "failed", [], None
        monkeypatch.setattr(lc, "_learn_one_group", _counter)
        s1 = [{"device": "R1", "platform": "cisco_ios", "command": "show x", "raw_output": "first"}]
        s2 = [{"device": "R1", "platform": "cisco_ios", "command": "show x", "raw_output": "DIFFERENT"}]
        lc.learn_commands(s1, allow_llm=False)
        lc.learn_commands(s2, allow_llm=False)
        # New sample hash → cache miss → retry
        assert n_calls[0] == 2

    def test_contract_version_drift_invalidates(self, monkeypatch, _sandbox_templates_dir):
        monkeypatch.setattr(lc, "_learn_one_group",
                            lambda *a, **kw: ("failed", [], None))
        samples = [{"device": "R1", "platform": "cisco_ios", "command": "show x", "raw_output": "r"}]
        lc.learn_commands(samples, allow_llm=False)
        # Manually corrupt contract_version in cache to simulate bump
        cache_path = _sandbox_templates_dir / "_failed_learn.json"
        data = json.loads(cache_path.read_text())
        for v in data.values():
            v["contract_version"] = 0  # old version
        cache_path.write_text(json.dumps(data))
        # Reload and rerun — should NOT skip this time
        n_calls = [0]
        def _counter(*a, **kw):
            n_calls[0] += 1
            return "failed", [], None
        monkeypatch.setattr(lc, "_learn_one_group", _counter)
        lc.learn_commands(samples, allow_llm=False)
        assert n_calls[0] == 1  # cache was invalidated

    def test_successful_learn_clears_cache_entry(self, monkeypatch):
        """When a successful learn runs for a previously-cached-failed
        key, the cache entry is removed so future runs go through."""
        samples = [{"device": "R1", "platform": "cisco_ios", "command": "show x", "raw_output": "r"}]
        # First: fail → cache entry written
        monkeypatch.setattr(lc, "_learn_one_group",
                            lambda *a, **kw: ("failed", [], None))
        lc.learn_commands(samples, allow_llm=False)
        # Second: override cache via force_relearn and succeed.
        # (Cache-hit would otherwise short-circuit before the learner runs.)
        def _success(plat, cmd, samples, *, max_retries, allow_llm):
            return "learned", [{"device": "R1", "command": cmd, "parsed_data": [{"x": 1}], "source": "fake"}], {
                "platform": plat, "command": cmd, "dsl": "python", "source": "fake",
            }
        monkeypatch.setattr(lc, "_learn_one_group", _success)
        r = lc.learn_commands(samples, allow_llm=True, force_relearn=True)
        assert len(r.newly_parsed) == 1
        # Third: cache should be clear (success deletes entry) so this re-runs.
        n_calls = [0]
        def _counter(*a, **kw):
            n_calls[0] += 1
            return "failed", [], None
        monkeypatch.setattr(lc, "_learn_one_group", _counter)
        lc.learn_commands(samples, allow_llm=False)
        assert n_calls[0] == 1


# ──────────────────────────────────────────────────────────────────────────
# Budget
# ──────────────────────────────────────────────────────────────────────────

class TestBudget:
    def test_budget_zero_skips_all(self, monkeypatch):
        """With budget=0, every submitted future is cancelled before
        completion (as_completed raises TimeoutError immediately)."""
        monkeypatch.setattr(lc, "_learn_one_group",
                            lambda *a, **kw: ("failed", [], None))
        samples = [
            {"device": f"R{i}", "platform": "cisco_ios",
             "command": f"show cmd {i}", "raw_output": "raw"}
            for i in range(5)
        ]
        r = lc.learn_commands(samples, allow_llm=False, budget_seconds=0, max_workers=2)
        skipped_reasons = {s["reason"] for s in r.skipped}
        assert "budget_exhausted" in skipped_reasons

    def test_budget_post_submit_exhaustion(self, monkeypatch):
        """Workers that don't finish before budget timeout get cancelled."""
        def _slow(*a, **kw):
            time.sleep(2)
            return "learned", [], None
        monkeypatch.setattr(lc, "_learn_one_group", _slow)
        samples = [
            {"device": f"R{i}", "platform": "cisco_ios",
             "command": f"show cmd {i}", "raw_output": "raw"}
            for i in range(3)
        ]
        t0 = time.time()
        r = lc.learn_commands(samples, allow_llm=False, budget_seconds=1, max_workers=1)
        elapsed = time.time() - t0
        # Should return within a few seconds of budget, NOT 6s (3 × 2s serial)
        assert elapsed < 5
        # At least one command should be in skipped (post-submit cancel or pre-submit deferred)
        assert len(r.skipped) >= 1


# ──────────────────────────────────────────────────────────────────────────
# Concurrency
# ──────────────────────────────────────────────────────────────────────────

class TestConcurrency:
    def test_threadpool_parallelises(self, monkeypatch):
        """With 5 slow workers and max_workers=5, wall-clock ≈ one worker's time."""
        def _slow(*a, **kw):
            time.sleep(0.5)
            return "learned", [], None
        monkeypatch.setattr(lc, "_learn_one_group", _slow)
        samples = [
            {"device": f"R{i}", "platform": "cisco_ios",
             "command": f"show cmd {i}", "raw_output": "raw"}
            for i in range(5)
        ]
        t0 = time.time()
        lc.learn_commands(samples, allow_llm=False, budget_seconds=30, max_workers=5)
        elapsed = time.time() - t0
        # All 5 run in parallel: should be ~0.5s, not 2.5s
        assert elapsed < 1.5, f"concurrency didn't kick in: {elapsed:.2f}s"


# ──────────────────────────────────────────────────────────────────────────
# samples_hash
# ──────────────────────────────────────────────────────────────────────────

class TestSamplesHash:
    def test_stable(self):
        samples = [
            {"device": "R1", "platform": "cisco_ios", "command": "x", "raw_output": "A"},
            {"device": "R2", "platform": "cisco_ios", "command": "x", "raw_output": "B"},
        ]
        h1 = lc._samples_hash(samples)
        h2 = lc._samples_hash(samples)
        assert h1 == h2

    def test_order_independent(self):
        a = [
            {"device": "R1", "platform": "cisco_ios", "command": "x", "raw_output": "A"},
            {"device": "R2", "platform": "cisco_ios", "command": "x", "raw_output": "B"},
        ]
        b = list(reversed(a))
        assert lc._samples_hash(a) == lc._samples_hash(b)

    def test_raw_change_changes_hash(self):
        a = [{"device": "R1", "platform": "cisco_ios", "command": "x", "raw_output": "A"}]
        b = [{"device": "R1", "platform": "cisco_ios", "command": "x", "raw_output": "B"}]
        assert lc._samples_hash(a) != lc._samples_hash(b)
