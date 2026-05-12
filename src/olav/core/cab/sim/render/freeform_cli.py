"""Native freeform_cli renderer — DraftChangePlan → CabTcf, zero DB.

R-CAB-THREE-STAGE cleanup 2026-05-13: replaces the legacy
``tcf_writer._render_freeform_cli`` + ``render_tcf_from_change_plan``
pair. Reads every fact from ``draft`` directly — no ``_db_facts``,
no Markdown plan parsing, no shared-state side effects.

Inputs:
  * draft.devices_in_scope         — device names
  * draft.facts_collected.devices  — per-device platform / loopback / local_as
  * draft.facts_collected.topology_edges — L2 adjacencies (copied through)
  * draft.intent_args              — cli_per_device, rollback_per_device,
                                     post_checks, optional pre_checks

Output: a ready-to-write CabTcf instance.
"""
from __future__ import annotations

from datetime import datetime, UTC

from olav.core.cab.schemas import DraftChangePlan
from olav.core.cab.tcf_schema import (
    CabTcf,
    CliBlock,
    Device,
    ExecutionRecord,
    Intent,
    PostCheck,
    PreCheck,
    TcfLink,
    TvtRow,
)


def render(draft: DraftChangePlan, lab_subnet: str, change_id: str) -> CabTcf:
    facts_idx = {d.name: d for d in draft.facts_collected.devices}
    args = draft.intent_args

    cli_per_device: dict[str, list[str]] = args.get("cli_per_device") or {}
    rollback_per_device: dict[str, list[str]] = args.get("rollback_per_device") or {}
    pre_checks_in: list[dict] = args.get("pre_checks") or []
    post_checks_in: list[dict] = args.get("post_checks") or []

    devices: list[Device] = []
    for name in draft.devices_in_scope:
        df = facts_idx.get(name)
        devices.append(Device(
            name=name,
            platform=(df.platform if df else "unknown"),
            prod_loopback=(df.loopback if df else None),
            prod_asn=(df.local_as if df else None),
        ))

    impl: list[CliBlock] = []
    rollback: list[CliBlock] = []
    for name in draft.devices_in_scope:
        d_cli = cli_per_device.get(name) or []
        d_rb = rollback_per_device.get(name) or []
        if isinstance(d_cli, str):
            d_cli = d_cli.splitlines()
        if isinstance(d_rb, str):
            d_rb = d_rb.splitlines()
        if d_cli:
            impl.append(CliBlock(device=name, phase=1, action="configure", cli=list(d_cli)))
        if d_rb:
            rollback.append(CliBlock(device=name, phase=1, action="configure", cli=list(d_rb)))

    pre_check: list[PreCheck] = []
    for i, pc in enumerate(pre_checks_in, start=1):
        if not isinstance(pc, dict):
            continue
        dev = pc.get("device")
        if dev not in draft.devices_in_scope:
            continue
        pre_check.append(PreCheck(
            device=dev,
            check_id=pc.get("check_id") or f"PR-{dev}-{i:02d}",
            description=pc.get("description") or "(no description)",
            command=pc["command"],
            expected_pattern=pc.get("expected_pattern", ""),
            must_match=bool(pc.get("must_match", True)),
        ))

    post_check: list[PostCheck] = []
    for i, pc in enumerate(post_checks_in, start=1):
        if not isinstance(pc, dict):
            continue
        dev = pc.get("device")
        if dev not in draft.devices_in_scope:
            continue
        post_check.append(PostCheck(
            device=dev,
            check_id=pc.get("check_id") or f"PC-{dev}-{i:02d}",
            description=pc.get("description") or "(no description)",
            command=pc["command"],
            expected_pattern=pc.get("expected_pattern", ""),
        ))

    tvt = [TvtRow(
        test_id="TC-freeform-verify",
        description=(
            f"All post_check evidence must match expected patterns "
            f"({len(post_check)} check{'s' if len(post_check) != 1 else ''})"
        ),
        expected="all-post-checks-pass",
        evidence_check_ids=[pc.check_id for pc in post_check],
        severity="info",
    )]

    topology_links = [
        TcfLink(
            source_device=e.source_device,
            source_interface=e.source_interface,
            destination_device=e.destination_device,
            destination_interface=e.destination_interface,
            discovery_protocol=e.discovery_protocol,
        )
        for e in draft.facts_collected.topology_edges
    ]

    return CabTcf(
        change_id=change_id,
        title=(draft.user_prompt[:80] or change_id),
        created_by="sim",
        created_at=datetime.now(tz=UTC),
        risk_class="medium",
        intent=Intent(type="freeform_cli", lab_subnet=lab_subnet),
        devices=devices,
        topology_links=topology_links,
        pre_check=pre_check,
        implementation=impl,
        rollback=rollback,
        post_check=post_check,
        tvt=tvt,
        required_tests=["TC-freeform-verify"],
        lab=ExecutionRecord(),
        prod=ExecutionRecord(),
    )
