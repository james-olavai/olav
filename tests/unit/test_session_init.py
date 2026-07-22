"""Per-agent session-init hooks (olav.session_init) — dev_docs/100 §4.6.

Generic domain launch callback: the platform calls every registered hook with
the resolved agent_id at agent construction, before LLM/graph build.
"""

from __future__ import annotations

import types


def test_run_session_init_invokes_hooks(monkeypatch):
    from olav.core import session_init

    calls = []

    class _EP:
        name = "fake"

        def load(self):
            return lambda agent_id: calls.append(agent_id)

    monkeypatch.setattr(session_init, "entry_points", lambda group: [_EP()], raising=False)
    # patch the importlib symbol the function imports locally
    import importlib.metadata as md

    monkeypatch.setattr(md, "entry_points", lambda group=None: [_EP()])
    session_init.run_session_init("presales")
    assert calls == ["presales"]


def test_run_session_init_swallows_hook_errors(monkeypatch):
    from olav.core import session_init

    class _EP:
        name = "boom"

        def load(self):
            def _hook(agent_id):
                raise RuntimeError("nope")
            return _hook

    import importlib.metadata as md

    monkeypatch.setattr(md, "entry_points", lambda group=None: [_EP()])
    # must not raise
    session_init.run_session_init("core")


def test_olavagent_init_calls_session_init(monkeypatch):
    """Wiring: OLAVAgent.__init__ fires run_session_init from a real construction."""
    import olav.core.session_init as si

    recorded = []
    monkeypatch.setattr(si, "run_session_init", lambda agent_id: recorded.append(agent_id))

    from olav.agents.agent import OLAVAgent

    try:
        OLAVAgent(agent_id="core")
    except Exception:
        # downstream construction (LLM/workspace) may fail in the test env; the
        # session_init call fires earlier, which is what we assert.
        pass
    assert recorded == ["core"]
