"""§7.1 first-run empty-state checks (dev_docs/99).

Platform side: ``_run_extension_first_run_checks()`` discovers the
``olav.first_run_checks`` entry-point group and queues findings via
``tui_overlay.add_first_run_finding``. Covers:
1. registered providers' findings reach the welcome-screen slot
2. a broken provider is skipped without blocking the others (never raises)
3. falsy returns queue nothing
4. §3.3's embedding finding and §7.1 findings coexist (add doesn't clobber)
5. wiring: _ensure_bootstrapped runs extension checks on EVERY launch
   (unlike the fresh-bootstrap-only §3.3 embedding probe)
"""

from __future__ import annotations

import asyncio
import json

import olav.cli.main as main_mod
import olav.cli.tui_overlay as overlay


class _FakeEntryPoint:
    def __init__(self, name, func):
        self.name = name
        self._func = func

    def load(self):
        return self._func


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# discovery + collection
# ---------------------------------------------------------------------------


def test_findings_from_providers_reach_slot(monkeypatch) -> None:
    overlay.consume_first_run_finding()  # clear leftovers
    eps = [
        _FakeEntryPoint("a", lambda: "netops has no device data yet"),
        _FakeEntryPoint("b", lambda: None),  # nothing to say
        _FakeEntryPoint("c", lambda: "second finding"),
    ]
    monkeypatch.setattr(main_mod, "entry_points", lambda group: eps)

    main_mod._run_extension_first_run_checks()

    combined = overlay.consume_first_run_finding()
    assert "netops has no device data yet" in combined
    assert "second finding" in combined


def test_broken_provider_skipped_others_survive(monkeypatch) -> None:
    overlay.consume_first_run_finding()

    def _boom():
        raise RuntimeError("extension bug")

    eps = [
        _FakeEntryPoint("broken", _boom),
        _FakeEntryPoint("good", lambda: "still works"),
    ]
    monkeypatch.setattr(main_mod, "entry_points", lambda group: eps)

    main_mod._run_extension_first_run_checks()  # must not raise

    assert "still works" in overlay.consume_first_run_finding()


def test_no_providers_no_finding(monkeypatch) -> None:
    overlay.consume_first_run_finding()
    monkeypatch.setattr(main_mod, "entry_points", lambda group: [])

    main_mod._run_extension_first_run_checks()

    assert overlay.consume_first_run_finding() is None


def test_extension_finding_does_not_clobber_embedding_finding(monkeypatch) -> None:
    overlay.consume_first_run_finding()
    overlay.set_first_run_finding("Embedding backend unavailable")  # §3.3 queued first
    eps = [_FakeEntryPoint("netops", lambda: "no device data")]
    monkeypatch.setattr(main_mod, "entry_points", lambda group: eps)

    main_mod._run_extension_first_run_checks()

    combined = overlay.consume_first_run_finding()
    assert "Embedding backend unavailable" in combined
    assert "no device data" in combined


# ---------------------------------------------------------------------------
# tui_overlay multi-finding semantics
# ---------------------------------------------------------------------------


def test_add_appends_set_replaces() -> None:
    overlay.consume_first_run_finding()
    overlay.add_first_run_finding("one")
    overlay.add_first_run_finding("two")
    assert overlay.consume_first_run_finding() == "one\n⚠ two"

    overlay.add_first_run_finding("stale")
    overlay.set_first_run_finding("fresh")  # set replaces everything queued
    assert overlay.consume_first_run_finding() == "fresh"

    overlay.set_first_run_finding(None)  # falsy set clears
    assert overlay.consume_first_run_finding() is None


# ---------------------------------------------------------------------------
# wiring — runs on every launch, not only fresh bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_runs_extension_checks_even_without_fresh_init(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    (tmp_path / ".olav" / "config" / "api.json").write_text(
        json.dumps({"llm": {"api_key": "sk-existing"}}), encoding="utf-8"
    )

    called = {"ext": False, "health": False}
    monkeypatch.setattr(
        main_mod, "_run_extension_first_run_checks", lambda: called.__setitem__("ext", True)
    )
    monkeypatch.setattr(
        main_mod, "_check_first_run_health", lambda: called.__setitem__("health", True)
    )

    assert _run(main_mod._ensure_bootstrapped()) is True
    assert called["ext"] is True, "extension checks must run on every launch"
    assert called["health"] is False, "embedding probe stays fresh-bootstrap-only"
