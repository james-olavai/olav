"""Governance — redaction availability + opt-out discoverability.

Deliberately does NOT importorskip netconan (unlike test_redaction.py):
these gates must hold precisely in environments where netconan is absent.

1. olav-netops declares netconan as a HARD dependency — its collect/import
   paths are the redaction consumers, and redaction defaults ON, so a
   netops install without netconan warns loudly and writes plaintext on
   every network import (the demo-env failure mode, 2026-07-18).
2. The netconan-missing warning must name the api.json opt-out
   ("redaction": {"enabled": false}) — it originally only named env vars,
   so operators couldn't discover the config-file path that
   _load_config_overrides has supported all along.
"""
from __future__ import annotations

import sys
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parents[2]


def test_netops_declares_netconan_hard_dependency():
    with (REPO / "olav-netops" / "pyproject.toml").open("rb") as fh:
        deps: list[str] = tomllib.load(fh)["project"]["dependencies"]
    assert any(d.startswith("netconan") for d in deps), (
        "olav-netops must declare netconan as a hard dependency — its "
        "collect/import paths consume olav.core.redaction, which defaults "
        "ON and fail-opens (plaintext credentials on disk + a SECURITY "
        "warning) when the lib is missing."
    )


def test_api_json_redaction_section_reaches_scrub(tmp_path, monkeypatch):
    """Regression: _load_config_overrides called get_config() and then
    `full.get("redaction") if isinstance(full, dict)` — but get_config()
    returns a ConfigLoader, never a dict, so the documented api.json
    redaction section was dead code (only OLAV_REDACTION env ever worked).
    Wire a real api.json with enabled=false through the real ConfigLoader
    and assert scrub leaves credentials untouched."""
    import json

    import olav.core.config as config_mod
    import olav.core.redaction as red

    cfg_dir = tmp_path / ".olav" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "api.json").write_text(
        json.dumps({"redaction": {"enabled": False}}), encoding="utf-8"
    )
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_mod.ConfigLoader, "_loaded", False)
    monkeypatch.setattr(config_mod.ConfigLoader, "_instance", None)
    monkeypatch.setattr(config_mod, "_config", None)
    monkeypatch.delenv("OLAV_REDACTION", raising=False)

    secret = "username admin password 7 02050D480809"
    text, findings = red.scrub(secret, workspace_root=tmp_path)  # no cfg= → loader path
    assert text == secret, (
        "api.json redaction.enabled=false must disable scrubbing via the "
        "real config loader (not only the OLAV_REDACTION env var)"
    )


def test_missing_netconan_warning_names_api_json_opt_out(tmp_path, monkeypatch, caplog):
    """Exercise the real netconan-missing path: the warning must point at
    the api.json opt-out, not only env vars."""
    import olav.core.redaction as red

    # Make `from netconan.anonymize_files import ...` raise ImportError even
    # when netconan is installed.
    monkeypatch.setitem(sys.modules, "netconan", None)
    monkeypatch.setitem(sys.modules, "netconan.anonymize_files", None)
    monkeypatch.setattr(red, "_NETCONAN_MISSING_WARNED", False)
    monkeypatch.delenv("OLAV_REDACTION_STRICT", raising=False)

    with caplog.at_level("WARNING", logger="olav.core.redaction"):
        text, findings = red.scrub(
            "username admin password 7 02050D480809",
            workspace_root=tmp_path,
            cfg={"enabled": True},
        )

    assert findings.degraded is True
    assert text == "username admin password 7 02050D480809"  # fail-open, unchanged
    warning = "\n".join(r.getMessage() for r in caplog.records)
    assert "api.json" in warning and '"enabled": false' in warning, (
        "netconan-missing warning must name the api.json redaction opt-out"
    )
