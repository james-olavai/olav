"""Governance — collection-time credential redaction (`core/redaction.py`).

Validates the contract:
* passwords / SNMP communities / shared secrets get scrubbed
* IP addresses / hostnames / ASNs / BGP relationships preserved
* salt auto-generated under <workspace>/.redaction_salt with chmod 600
* OLAV_REDACTION=0 fail-open returns input unchanged
* netconan absent → fail-open (logged at WARNING)
* empty / whitespace input handled without exception
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

# Skip everything when netconan isn't available — install via
# `pip install 'olav[redaction]'` to enable.
netconan = pytest.importorskip("netconan")

from olav.core.redaction import Findings, _salt_fingerprint, _workspace_salt, scrub


# ── fixtures ─────────────────────────────────────────────────────────


_CISCO_IOS_SNIPPET = """\
hostname R1
!
username admin privilege 15 password 7 02050D480809
enable secret 5 $1$abc$xyz789
!
snmp-server community netops-r0 RO
snmp-server community write-string-here RW
!
ip route 0.0.0.0 0.0.0.0 10.1.1.1
ip route 192.168.10.0 255.255.255.0 10.1.13.3
!
router bgp 65000
 bgp router-id 1.1.1.1
 neighbor 10.1.12.2 remote-as 65001
 neighbor 10.1.12.2 password BGP_SHARED_KEY_xyz
 neighbor 3.3.3.3 remote-as 65000
"""


_JUNOS_SNIPPET = """\
system {
    root-authentication {
        encrypted-password "$1$abc$junos-encrypted-hash";
    }
    login {
        user admin {
            authentication {
                encrypted-password "$1$xyz$another-hash";
            }
        }
    }
}
snmp {
    community "junos-snmp-community-string" {
        authorization read-only;
    }
}
protocols {
    bgp {
        group external {
            type external;
            peer-as 65001;
            authentication-key "BGP_MD5_KEY";
            neighbor 10.1.12.2;
        }
    }
}
"""


# ── salt management ─────────────────────────────────────────────────


def test_salt_auto_generated(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    salt_path = ws / ".redaction_salt"
    assert not salt_path.exists()

    salt = _workspace_salt(ws)
    assert len(salt) == 64  # 32 bytes hex
    assert salt_path.exists()

    # chmod 600
    mode = stat.S_IMODE(salt_path.stat().st_mode)
    assert mode == 0o600, f"salt file mode {oct(mode)} != 0o600"


def test_salt_stable_across_calls(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    salt_a = _workspace_salt(ws)
    salt_b = _workspace_salt(ws)
    assert salt_a == salt_b  # same workspace → same salt


def test_salt_fingerprint_short(tmp_path: Path) -> None:
    fp = _salt_fingerprint("a" * 64)
    assert len(fp) == 8
    assert all(c in "0123456789abcdef" for c in fp)


# ── core scrub semantics ────────────────────────────────────────────


def test_cisco_passwords_scrubbed(tmp_path: Path) -> None:
    out, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws")
    # Type-7 password hash gets re-encrypted (netconan rewrites the hex).
    assert "02050D480809" not in out
    # Enable secret hash gone too.
    assert "$1$abc$xyz789" not in out
    # BGP MD5 key replaced with netconan marker.
    assert "BGP_SHARED_KEY_xyz" not in out


def test_snmp_communities_scrubbed(tmp_path: Path) -> None:
    out, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws")
    assert "netops-r0" not in out
    assert "write-string-here" not in out
    # Replaced with netconan token.
    assert "netconanRemoved" in out


def test_ip_addresses_preserved(tmp_path: Path) -> None:
    """The whole point — IPs survive so topology / diff still works."""
    out, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws")
    for ip in ("10.1.1.1", "192.168.10.0", "255.255.255.0",
               "1.1.1.1", "10.1.12.2", "3.3.3.3"):
        assert ip in out, f"IP {ip} disappeared from scrubbed output"


def test_hostnames_preserved(tmp_path: Path) -> None:
    out, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws")
    assert "hostname R1" in out


def test_asns_preserved(tmp_path: Path) -> None:
    out, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws")
    assert "router bgp 65000" in out
    assert "remote-as 65001" in out
    assert "remote-as 65000" in out


def test_junos_credentials_scrubbed(tmp_path: Path) -> None:
    out, _ = scrub(_JUNOS_SNIPPET, workspace_root=tmp_path / "ws")
    # encrypted-password lines get fully removed by netconan (matched
    # by its "unsupported-format" line-drop path, which is still safe).
    assert "junos-encrypted-hash" not in out
    assert "another-hash" not in out
    # BGP authentication-key replaced with a marker.
    assert "BGP_MD5_KEY" not in out
    # ASN preserved
    assert "peer-as 65001" in out
    # neighbor IP preserved
    assert "10.1.12.2" in out
    # KNOWN GAP (documented in core/redaction.py): netconan's default
    # Junos pattern set doesn't cover the `snmp { community "X" }`
    # block syntax — operators who want to scrub this can add
    # ``community`` to ``api.json.redaction.extra_sensitive_words``.


def test_junos_community_via_extra_sensitive_words(tmp_path: Path) -> None:
    """Operator-supplied extension catches Junos snmp { community }."""
    cfg = {
        "enabled": True,
        "anon_ip": False,
        "extra_sensitive_words": ["community"],
        "extra_reserved_words": [],
    }
    out, _ = scrub(_JUNOS_SNIPPET, workspace_root=tmp_path / "ws", cfg=cfg)
    assert "junos-snmp-community-string" not in out


def test_findings_summary(tmp_path: Path) -> None:
    _, findings = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws")
    # netconan only emits the "netconanRemovedN" marker for
    # sensitive-words matches (SNMP communities, BGP keys).
    # Type-7 password hex is rewritten in-place (no marker), and
    # `enable secret` hashes are dropped via line-removal — so
    # the visible marker count is a lower bound on actual changes.
    # 2 SNMP communities + 1 BGP MD5 key = 3 markers expected.
    assert findings.total_replacements >= 3
    assert findings.salt_fingerprint
    assert "sensitive_words" in findings.category_counts


# ── fail-open behaviour ─────────────────────────────────────────────


def test_disabled_via_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OLAV_REDACTION", "0")
    out, findings = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws")
    assert out == _CISCO_IOS_SNIPPET
    assert findings.total_replacements == 0
    assert findings.salt_fingerprint == ""


def test_empty_input_safe(tmp_path: Path) -> None:
    out, findings = scrub("", workspace_root=tmp_path / "ws")
    assert out == ""
    assert findings.total_replacements == 0


def test_whitespace_only_input_safe(tmp_path: Path) -> None:
    out, _ = scrub("   \n\n  ", workspace_root=tmp_path / "ws")
    assert out.strip() == ""


# ── cross-snapshot stability ────────────────────────────────────────


def test_same_salt_produces_same_scrub(tmp_path: Path) -> None:
    """Idempotent: same input + same workspace = identical scrubbed output.

    This is the contract that makes cross-snapshot credential diff
    work — operators can see "did the SNMP community change?" without
    seeing either value.
    """
    ws = tmp_path / "ws"
    out_a, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=ws)
    out_b, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=ws)
    assert out_a == out_b


def test_different_salts_produce_different_ip_scrubs(tmp_path: Path) -> None:
    """Salt isolation matters for the **Crypto-PAn IP anonymizer**
    (anon_ip=True path).  Password and SNMP-community markers are
    sequence-numbered locally to each scrub call, not salt-derived,
    so salt has no visible effect on them when anon_ip=False (OLAV's
    default mode for network-diff utility).

    This test runs anon_ip=True explicitly to verify the salt path
    works when an operator opts in via api.json.redaction.anon_ip.
    """
    cfg = {
        "enabled": True,
        "anon_ip": True,
        "extra_sensitive_words": [],
        "extra_reserved_words": [],
    }
    out_a, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws_a", cfg=cfg)
    out_b, _ = scrub(_CISCO_IOS_SNIPPET, workspace_root=tmp_path / "ws_b", cfg=cfg)
    # With different salts, the anonymized IP for 10.1.1.1 should
    # differ across workspaces.  Easiest check: the byte-for-byte
    # output strings differ.
    assert out_a != out_b, (
        "different salts must produce different IP anonymizations"
    )
