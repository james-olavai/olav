"""doctor must report the auth mode, and whether this install can serve it.

Two real incidents motivate it:

* A clean-VM install came out of a successful `olav init` and a 9/9 `olav doctor`
  with every query path dead — init had written `auth.mode=token`, whose provider
  lives in olav-ent (dev_docs/115 §1). Nothing in doctor looked at auth.
* An operator who had set `mode: none` found it as `token` afterwards, because
  init sets token when it creates the admin user. Without doctor showing the
  mode, the only way to notice is to read api.json.

`auth.mode` is read from .olav/config/api.json with an OLAV_AUTH_MODE env
override, default "none".
"""

from __future__ import annotations

import pytest

from olav.cli.commands.doctor import DoctorCommand


class TestAuthCheck:
    def test_reports_a_servable_mode_as_ok_with_the_provider_named(self, monkeypatch):
        monkeypatch.delenv("OLAV_AUTH_MODE", raising=False)
        monkeypatch.setattr(
            "olav.core.config.ConfigLoader",
            lambda: type("C", (), {"auth": type("A", (), {"mode": "none"})()})(),
        )
        r = DoctorCommand()._check_auth()
        assert r["ok"] is True
        assert "mode=none" in r["detail"]
        assert "OSIdentityProvider" in r["detail"], (
            "naming the provider is what makes a silent mode change visible"
        )

    def test_flags_a_mode_this_install_cannot_serve(self, monkeypatch):
        """The bricked-install case: init wrote token, olav-ent is absent."""
        monkeypatch.delenv("OLAV_AUTH_MODE", raising=False)
        monkeypatch.setattr(
            "olav.core.config.ConfigLoader",
            lambda: type("C", (), {"auth": type("A", (), {"mode": "token"})()})(),
        )

        def _boom(mode=None):
            raise NotImplementedError(
                "auth.mode='token' requires olav-ent (the token/server/ldap "
                "providers moved to olav.enterprise.auth)"
            )

        monkeypatch.setattr("olav.core.auth.provider.get_auth_provider", _boom)
        r = DoctorCommand()._check_auth()
        assert r["ok"] is False
        assert "cannot be served" in r["detail"]
        assert "olav-ent" in r["fix"] and "auth.mode" in r["fix"], (
            "the fix line must name both ways out"
        )

    def test_names_the_env_override_as_the_source(self, monkeypatch):
        """Otherwise an operator edits api.json and cannot see why it has no
        effect."""
        monkeypatch.setenv("OLAV_AUTH_MODE", "none")
        monkeypatch.setattr(
            "olav.core.config.ConfigLoader",
            lambda: type("C", (), {"auth": type("A", (), {"mode": "none"})()})(),
        )
        r = DoctorCommand()._check_auth()
        assert "OLAV_AUTH_MODE env" in r["detail"]

    def test_unreadable_config_is_reported_not_raised(self, monkeypatch):
        def _boom():
            raise RuntimeError("no config")

        monkeypatch.setattr("olav.core.config.ConfigLoader", _boom)
        r = DoctorCommand()._check_auth()
        assert r["ok"] is False and "config unreadable" in r["detail"]


def test_auth_is_wired_into_the_check_list():
    """A check that exists but is never run is worse than no check —
    dev_docs/97's recurring failure mode."""
    from pathlib import Path

    src = Path(DoctorCommand.__module__.replace(".", "/") + ".py")
    if not src.exists():
        import olav.cli.commands.doctor as _d
        src = Path(_d.__file__)
    text = src.read_text(encoding="utf-8")
    body = text[text.index("checks = ["):text.index("_check_services")]
    assert "self._check_auth()" in body, (
        "_check_auth must be in the list doctor actually executes"
    )
