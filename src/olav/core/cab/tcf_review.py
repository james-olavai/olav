"""Patch O'-A — lab-side review of spec.implementation as deployable
production CLI.

Returns a list of ``ProdReviewFinding`` advisory items.  Currently
**deterministic rule-based** (Tier A): per-vendor required-command
checklists.  An LLM-backed Tier C reviewer can be layered on top later
without changing the call site.

Why rules first:

  * Every CAB shop's "what does our prod baseline assume" question
    is shop-specific; the rules here capture **vendor-mandatory**
    items only (config that won't commit / session won't come up
    without these), not stylistic preferences.
  * Deterministic + zero-cost + easy to test in CI.
  * Findings are advisory — operator decides if a finding is a real
    issue or a baseline assumption for their environment.

The rules below cover ``ebgp_direct`` intent for ``juniper_junos`` and
``cisco_ios`` — the same intents R88-A / R89 / R90 already support.
Adding a new intent / vendor is one new entry in ``_RULES``.
"""

from __future__ import annotations

import re
from typing import Any

from .tcf_schema import CabTcf, ProdReviewFinding


# A rule is a callable: (cli_lines, device, intent) -> list[Finding].
# Each rule is independent and contributes its findings to the total.
_RuleFn = Any  # callable; loose typing avoids circular Pydantic import


def _join(cli_lines: list[str]) -> str:
    """Join a CliBlock's lines into a single searchable string."""
    return "\n".join(cli_lines or [])


# ── Junos eBGP rules ───────────────────────────────────────────────────


def _junos_check_local_as(cli: str, device: str) -> list[ProdReviewFinding]:
    if re.search(r"\bset\s+routing-options\s+autonomous-system\s+\d+", cli):
        return []
    return [ProdReviewFinding(
        severity="blocker",
        device=device,
        category="missing_command",
        description=(
            "Junos eBGP requires the local AS declared via "
            "'set routing-options autonomous-system <N>'.  Without it, "
            "'commit' rejects with 'must specify autonomous-system'."
        ),
        suggested_fix="set routing-options autonomous-system <local_asn>",
    )]


def _junos_check_router_id(cli: str, device: str) -> list[ProdReviewFinding]:
    if re.search(r"\bset\s+routing-options\s+router-id\s+", cli):
        return []
    return [ProdReviewFinding(
        severity="warn",
        device=device,
        category="assumes_baseline",
        description=(
            "No 'set routing-options router-id'.  If baseline already "
            "configures router-id (e.g., from loopback) this is fine; "
            "otherwise BGP picks a non-deterministic ID."
        ),
        suggested_fix="set routing-options router-id <prod_loopback>",
    )]


def _junos_check_export_policy(cli: str, device: str) -> list[ProdReviewFinding]:
    has_export = re.search(r"\bset\s+protocols\s+bgp\s+group\s+\S+\s+export\s+\S+", cli)
    if has_export:
        return []
    return [ProdReviewFinding(
        severity="warn",
        device=device,
        category="missing_command",
        description=(
            "Junos BGP group has no 'export <policy>'.  Default is "
            "reject-all — session establishes but no routes advertised. "
            "Often a real bug if the change's intent is to share routes."
        ),
        suggested_fix=(
            "set protocols bgp group <grp> export <policy>; "
            "set policy-options policy-statement <policy> term ..."
        ),
    )]


def _junos_check_interface_configured(
    cli: str, device: str, neighbor_ips: set[str]
) -> list[ProdReviewFinding]:
    """If neighbor IPs are referenced but no 'set interfaces ... family
    inet address ...' line — assume baseline interface, flag as warn."""
    if not neighbor_ips:
        return []
    if re.search(r"\bset\s+interfaces\s+\S+\s+unit\s+\d+\s+family\s+inet\s+address\s+", cli):
        return []
    return [ProdReviewFinding(
        severity="warn",
        device=device,
        category="assumes_baseline",
        description=(
            f"BGP references neighbor(s) {sorted(neighbor_ips)} but no "
            f"'set interfaces ... family inet address ...' is in the "
            f"change.  Assuming the link interface + IP exists in "
            f"baseline config; verify before deploy."
        ),
        suggested_fix="(none if baseline; otherwise add interface assignment)",
    )]


# ── IOS / IOS-XE eBGP rules ────────────────────────────────────────────


def _ios_check_address_family(cli: str, device: str) -> list[ProdReviewFinding]:
    """IOS BGP needs explicit 'address-family ipv4' + 'neighbor X
    activate' for the session to actually carry routes."""
    has_af = re.search(r"\baddress-family\s+ipv4\b", cli)
    has_activate = re.search(r"\bneighbor\s+\S+\s+activate\b", cli)
    findings: list[ProdReviewFinding] = []
    if not has_af:
        findings.append(ProdReviewFinding(
            severity="blocker",
            device=device,
            category="missing_command",
            description=(
                "IOS BGP block missing 'address-family ipv4'.  Session "
                "may form but won't carry IPv4 routes — depending on "
                "IOS version, even neighbor announcements may not work."
            ),
            suggested_fix="address-family ipv4",
        ))
    if not has_activate:
        findings.append(ProdReviewFinding(
            severity="blocker",
            device=device,
            category="missing_command",
            description=(
                "IOS BGP block missing 'neighbor <ip> activate' inside "
                "address-family ipv4.  Without this the neighbor stays "
                "in Idle/Active and won't reach Established."
            ),
            suggested_fix="address-family ipv4 / neighbor <peer_ip> activate",
        ))
    return findings


def _ios_check_router_id(cli: str, device: str) -> list[ProdReviewFinding]:
    if re.search(r"\bbgp\s+router-id\s+\S+", cli):
        return []
    return [ProdReviewFinding(
        severity="warn",
        device=device,
        category="assumes_baseline",
        description=(
            "IOS BGP block has no 'bgp router-id'.  IOS will auto-pick "
            "highest loopback IP if loopback is configured; otherwise "
            "highest physical interface — non-deterministic across "
            "reloads."
        ),
        suggested_fix="bgp router-id <prod_loopback>",
    )]


def _ios_check_interface_configured(
    cli: str, device: str, neighbor_ips: set[str]
) -> list[ProdReviewFinding]:
    if not neighbor_ips:
        return []
    if re.search(r"\binterface\s+\S+\b", cli) and re.search(
        r"\bip\s+address\s+\S+\s+\S+", cli
    ):
        return []
    return [ProdReviewFinding(
        severity="warn",
        device=device,
        category="assumes_baseline",
        description=(
            f"BGP references neighbor(s) {sorted(neighbor_ips)} but no "
            f"'interface ... / ip address ...' in the change. "
            f"Assuming link interface + IP exist in baseline."
        ),
        suggested_fix="(none if baseline; otherwise add interface block)",
    )]


# ── Common helpers ──────────────────────────────────────────────────────


_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")


def _extract_neighbor_ips(cli: str) -> set[str]:
    """All IPs cited as ``neighbor <IP>`` in the CLI."""
    found: set[str] = set()
    for m in re.finditer(r"\bneighbor\s+(\d{1,3}(?:\.\d{1,3}){3})\b", cli, re.I):
        found.add(m.group(1))
    return found


# ── Public API ──────────────────────────────────────────────────────────


def review_prod_cli(tcf: CabTcf) -> list[ProdReviewFinding]:
    """Review every device's implementation CLI for prod-deploy gaps.

    Walks each ``CliBlock``, applies the per-platform rules, and
    returns the union of findings.  Empty list = no flagged gaps
    (doesn't necessarily mean the spec is perfect — just that the
    rules saw no problems they know about).

    Per-rule findings are independent; severity reflects the
    rule's own confidence:

      * ``blocker``  → vendor will refuse commit / session won't form
      * ``warn``     → likely needed but baseline may already supply
      * ``info``     → observation worth noting
    """
    findings: list[ProdReviewFinding] = []
    by_device: dict[str, list[str]] = {}
    for blk in tcf.implementation:
        by_device.setdefault(blk.device, []).extend(blk.cli or [])

    devices_by_name = {d.name: d for d in tcf.devices}

    for device_name, lines in by_device.items():
        cli_text = _join(lines)
        device = devices_by_name.get(device_name)
        platform = (device.platform if device else "").lower()
        neighbor_ips = _extract_neighbor_ips(cli_text)

        if platform == "juniper_junos":
            findings.extend(_junos_check_local_as(cli_text, device_name))
            findings.extend(_junos_check_router_id(cli_text, device_name))
            findings.extend(_junos_check_export_policy(cli_text, device_name))
            findings.extend(_junos_check_interface_configured(
                cli_text, device_name, neighbor_ips,
            ))
        elif platform in ("cisco_ios", "cisco_iosxe", "cisco_xe"):
            findings.extend(_ios_check_address_family(cli_text, device_name))
            findings.extend(_ios_check_router_id(cli_text, device_name))
            findings.extend(_ios_check_interface_configured(
                cli_text, device_name, neighbor_ips,
            ))
        else:
            findings.append(ProdReviewFinding(
                severity="info",
                device=device_name,
                category="syntax_warning",
                description=(
                    f"Platform {platform!r} not in review rules — "
                    f"manual prod-CLI completeness check required."
                ),
                suggested_fix="(extend olav.core.cab.tcf_review)",
            ))

    return findings
