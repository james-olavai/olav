"""Pydantic models for the TCF (Test Case File) schema.

See ``dev_docs/65 § Schema (YAML, Pydantic-validated)``.

Design principles:
  * Tight on shape (lists / dicts / FK references) — Pydantic
    enforces these at load + emit time.
  * Loose on content — ``intent.type`` and per-domain fields are
    free-form strings. ``Device``, ``Intent``, ``JournalEntry`` use
    ``model_config["extra"] = "allow"`` so adding a new change type
    or per-device field doesn't require a schema bump.
  * Cross-FK validator on ``CabTcf`` ensures every device referenced
    in implementation / rollback / post_check exists in the devices
    list.

Schema versioning: ``CabTcf.schema_version`` tracks compatibility.
On a breaking change, bump the constant + add a ``model_validator``
that migrates older records to the new shape (or rejects them with
a clear error).
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Current schema version. Bump when fields are renamed or removed
# (additions are non-breaking thanks to ``extra="allow"``).
TCF_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Intent — free-form change type + arbitrary payload
# ---------------------------------------------------------------------------


class Intent(BaseModel):
    """The change being made.

    ``type`` is a free-form identifier (e.g. ``"ebgp_direct"``,
    ``"acl_update"``, ``"mtu_change"``, ``"vlan_add"``). Tools that
    handle specific change types match on it and raise clear errors
    when an unknown type arrives. We intentionally do NOT use a
    ``Literal`` enum here — adding a new change category should not
    require a schema bump.

    All other fields are accepted as-is (``extra="allow"``) so each
    change type can carry its own payload. Examples:

        intent: {type: ebgp_direct, lab_subnet: 172.16.99.0/30}
        intent: {type: acl_update,  acl_name: BLOCK_RFC1918}
        intent: {type: mtu_change,  target_mtu: 9216}
    """

    model_config = ConfigDict(extra="allow")
    type: str


# ---------------------------------------------------------------------------
# Device — required basics + per-change-type extras
# ---------------------------------------------------------------------------


class Device(BaseModel):
    """One node touched by the change.

    Required: ``name``, ``platform``. Other fields are optional —
    sim populates whatever is relevant for the change type.
    Per-change-type extras land in ``extras`` to keep the device
    record self-contained without polluting the main schema.

    ``platform`` is a free-form string. Tools that match on platform
    (e.g. ``generate_srl_lab_config`` only handles SRL containers)
    validate at use time. We don't enforce a Literal here so future
    platforms can be added without schema bumps.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    platform: str

    # Optional — sim populates what's relevant
    prod_intf: str | None = None
    prod_intf_ip: str | None = None
    prod_loopback: str | None = None
    prod_asn: int | None = None
    role: str = ""
    site: str = ""

    # Per-change-type per-device extras (e.g. ospf_area, mgmt_ip,
    # junos_version, vlan_membership). Open dict — domain-specific
    # tools read what they need.
    extras: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# CLI block — implementation + rollback share this shape
# ---------------------------------------------------------------------------


class CliBlock(BaseModel):
    """A list of CLI lines for one device, one phase, one action.

    Used identically in ``CabTcf.implementation`` and
    ``CabTcf.rollback`` — only the action verb differs (``configure``
    is typical for both apply and undo since vendors flag undo via
    ``delete``/``no`` prefixes inside the lines).

    ``phase`` is ``int | str`` because real changes mix numeric
    forward phases (``1``, ``2``) and string-tagged rollback IDs
    (``rb1``, ``rb2``, ``0-prereq``). Ordering within a phase is the
    list order; cross-phase ordering is by the ``int`` then ``str``
    sort of phase values.

    ``action`` is free-form (convention: ``configure`` / ``verify``
    / ``wait`` / etc.) so future change types can introduce new
    semantics without schema bumps.
    """

    device: str
    phase: int | str
    action: str = "configure"
    cli: list[str]


# ---------------------------------------------------------------------------
# Pre/Post-check — verification commands per device
# ---------------------------------------------------------------------------


class PostCheck(BaseModel):
    """One verification assertion the lab should run after deploy.

    ``expected_pattern`` is a string. Convention:
      * bare string  → substring match
      * ``re:<regex>`` prefix → regex match (tools dispatch)

    Tools rendering this for execution decide whether to run
    ``command`` verbatim on the platform CLI or to translate it
    (e.g., the lab translates a Junos ``show route`` into the SRL
    equivalent at run time).
    """

    device: str
    check_id: str
    description: str
    command: str
    expected_pattern: str


class PreCheck(BaseModel):
    """One precondition assertion the lab/prod runner verifies BEFORE
    pushing implementation config (ARCH-34).

    Same shape as PostCheck. Distinguished only by:
      * ``must_match: bool`` — True (default) means expected_pattern
        must be present in command output; False means it must be ABSENT
        (for "interface is unconfigured" / "subnet has no route" checks
        where the *absence* of a pattern is what proves freeness).

    Failure semantics: any pre_check failing => implementation MUST NOT
    push config.  HITL must intervene.  This is the structural fix for
    interface-collision and AS-collision incidents that were previously
    only catchable by reading the spec carefully.
    """

    device: str
    check_id: str
    description: str
    command: str
    expected_pattern: str
    must_match: bool = True


# ---------------------------------------------------------------------------
# TVT — Test Verification Tracker
# ---------------------------------------------------------------------------


class TvtRow(BaseModel):
    """One entry in the change's verification matrix.

    Filled in stages:
      * Sim writes the intent rows: test_id, description, expected,
        severity (default "info").
      * Lab fills ``actual_lab`` and updates ``status`` per row
        based on lab observation.
      * Prod ops (post-deploy) fills ``actual_prod``.

    ``severity`` and ``status`` are strings (not Literal) so different
    domains can use their own vocabulary (e.g. P0/P1/P2 instead of
    blocker/warn/info). Conventional values:

        severity: "blocker" | "warn" | "info"
        status:   "PENDING" | "PASS" | "FAIL" | "BLOCKED"
    """

    test_id: str
    description: str
    expected: str
    severity: str = "info"
    actual_lab: str | None = None
    actual_prod: str | None = None
    status: str = "PENDING"
    evidence_check_ids: list[str] = Field(default_factory=list)
    """Optional explicit link to ``post_check.check_id`` entries that
    prove this test row.  Sim populates this when emitting; lab
    consumes it deterministically (Patch N tier 1).  Backward-compatible
    default ``[]`` so old specs still parse."""


# ---------------------------------------------------------------------------
# Journal entry — per-step record of what lab/prod did
# ---------------------------------------------------------------------------


class JournalEntry(BaseModel):
    """One step in the lab or prod execution journal.

    Captures the tool / phase name, the args it was called with, a
    summary of the result, and a timestamp. This makes the lab's
    silent-override pattern visible — diff'ing the spec's
    implementation against what the journal actually executed
    surfaces typo corrections, IP plan adjustments, etc.

    ``args`` and ``result_summary`` are open dicts so each tool can
    record whatever's useful without schema rigidity.
    """

    model_config = ConfigDict(extra="allow")

    step: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime | None = None


# ---------------------------------------------------------------------------
# Cross-verification step verdict (R94)
# ---------------------------------------------------------------------------


class StepVerdict(BaseModel):
    """Per-step approve / reject result from cross-verifying spec.* vs
    lab.*_lab fields.

    Produced by ``tcf_diff_spec_vs_lab`` when comparing what sim wrote
    in the contract (e.g. ``implementation[0]`` = "set protocols bgp
    group ebgp-r4 ..." on Junos R1) against what the lab pushed as
    digital-twin evidence (e.g. ``lab.implementation_lab[0]`` =
    "set / network-instance default protocols bgp group ebgp-r4 ..."
    on SRL r1). The verdict + reason go to the CAB approver /
    sim-author for review.

    Naming convention: ``implementation_lab`` / ``rollback_lab`` /
    ``post_check_lab`` make the role explicit — sim writes the
    *real* prod-form CLI in the top-level lists; lab writes the
    *SRL twin* CLI as evidence. Production deployment uses sim's
    commands; lab's role is to provide twin-side proof per command,
    not a substitute deploy plan.
    """

    model_config = ConfigDict(extra="allow")

    spec_ref: str | None = None
    """Reference to the spec-side step being verified. Examples:
    ``"implementation[0]"``, ``"rollback[1]"``, ``"tvt[T1]"``,
    ``"post_check[bgp_up]"``. ``None`` when the verdict applies to a
    lab-only entry without a spec counterpart (verdict ``"extra"``)."""

    lab_ref: str | None = None
    """Reference to the corresponding lab-side entry. Examples:
    ``"implementation_lab[0]"``, ``"rollback_lab[1]"``,
    ``"post_check_lab[0]"``. ``None`` when the spec step has no lab
    counterpart (verdict ``"missing"``)."""

    verdict: str
    """Free-form verdict — convention:
    ``"approved"`` — lab covered the same intent
    ``"rejected"`` — semantic mismatch; sim or lab needs revision
    ``"missing"`` — spec has step, lab didn't execute it
    ``"extra"`` — lab did something not in spec
    ``"info"`` — informational note (broader / narrower / silent
    override). Tools dispatch on convention; unknown values render
    as-is."""

    reason: str = ""
    """Free-form text explaining the verdict. For ``approved``: usually
    short ("R89 skeleton covers all intent fields"). For
    ``rejected``: must explain what was wrong ("lab over-rolled —
    delete entire BGP vs sim's group-only delete")."""


# ---------------------------------------------------------------------------
# Execution record — lab side or prod side
# ---------------------------------------------------------------------------


class ExecutionRecord(BaseModel):
    """One execution of the change — by ops-lab in the digital twin
    or by prod ops on the production fleet.

    Lab-side use: ``lab_name`` and ``snapshot_id`` populated;
    ``journal`` records each tool call. Prod-side use: ``lab_name``
    and ``snapshot_id`` are None (production has no lab name); the
    journal records prod runbook steps.

    ``verdict`` is a string (not Literal) — convention is
    ``PENDING`` / ``PASS`` / ``FAIL`` / ``BLOCKED`` but tools that
    consume this should accept anything sensibly.

    R94 added the four ``*_lab`` parallel structures. Sim writes the
    prod-form contract (``implementation[]`` / ``rollback[]`` /
    ``post_check[]`` at top level — the *real* commands ops will run
    on prod); lab fills the SRL twin blocks here as evidence. The
    ``step_verdicts`` array is the cross-verification ledger linking
    each spec command to its lab-side proof. All four lab arrays
    default to empty for backward compatibility.
    """

    verdict: str = "PENDING"
    ran_at: datetime | None = None
    lab_name: str | None = None
    snapshot_id: str | None = None
    journal: list[JournalEntry] = Field(default_factory=list)
    diagnosis: str = ""
    recommendation: list[str] = Field(default_factory=list)

    # ── R94: lab-side digital-twin artefacts ────────────────────────
    implementation_lab: list["CliBlock"] = Field(default_factory=list)
    """Lab-side SRL CLI per node — the digital-twin evidence that
    sim's prod-form ``implementation[]`` was validated. Lab is
    expected to derive this *from* spec.implementation (translate
    Junos / IOS → SRL preserving semantic intent), not synthesize
    independently from intent. Production deployment uses sim's
    prod-form CLI; this field exists to prove the plan works on the
    twin per-command.
    """

    rollback_lab: list["CliBlock"] = Field(default_factory=list)
    """Lab-side SRL ``delete /`` CLI per node — twin-side evidence
    that sim's ``rollback[]`` plan reverses the change cleanly.
    Used to surface silent over-rollback (lab deleted more than
    sim's prod rollback would have).
    """

    post_check_lab: list["PostCheck"] = Field(default_factory=list)
    """Lab-side post-check commands actually run + observed pattern.
    Sim writes prod-form (e.g. ``show bgp summary`` on Junos); lab
    translates to ``sr_cli show network-instance default protocols
    bgp neighbor`` and records what it actually ran. Allows
    cross-verification that the translation preserved verification
    intent.
    """

    step_verdicts: list[StepVerdict] = Field(default_factory=list)
    """Cross-verification output: per-step approve / reject + reason.
    Produced by ``tcf_diff_spec_vs_lab`` when both sim contract and
    lab evidence are populated."""


# ---------------------------------------------------------------------------
# Top-level TCF — the contract artifact
# ---------------------------------------------------------------------------


class CabTcf(BaseModel):
    """The Change Approval Board change contract.

    Single source of truth for one change's lifecycle: sim writes
    most fields, lab fills the ``lab`` section + TVT.actual_lab +
    status, prod fills the ``prod`` section + TVT.actual_prod.

    Cross-FK validator (model_validator below) enforces that every
    device referenced in implementation / rollback / post_check
    exists in the devices list — catches sim typos at write time.
    """

    schema_version: int = TCF_SCHEMA_VERSION
    change_id: str
    title: str
    created_by: str
    created_at: datetime
    risk_class: str = "medium"

    intent: Intent
    devices: list[Device]
    pre_check: list[PreCheck] = Field(default_factory=list)
    implementation: list[CliBlock] = Field(default_factory=list)
    rollback: list[CliBlock] = Field(default_factory=list)
    post_check: list[PostCheck] = Field(default_factory=list)
    tvt: list[TvtRow] = Field(default_factory=list)

    required_tests: list[str] = Field(default_factory=list)
    optional_tests: list[str] = Field(default_factory=list)

    lab: ExecutionRecord = Field(default_factory=ExecutionRecord)
    prod: ExecutionRecord = Field(default_factory=ExecutionRecord)

    @model_validator(mode="after")
    def _check_device_fks(self) -> "CabTcf":
        """Every device referenced in implementation/rollback/post_check
        must exist in ``devices``. Prevents dangling-reference bugs at
        load time so downstream tools (lab, R89, R90) see a consistent
        graph.
        """
        names = {d.name for d in self.devices}
        offenders: list[str] = []

        for block in self.implementation:
            if block.device not in names:
                offenders.append(
                    f"implementation block phase={block.phase!r} "
                    f"references unknown device {block.device!r}"
                )
        for block in self.rollback:
            if block.device not in names:
                offenders.append(
                    f"rollback block phase={block.phase!r} "
                    f"references unknown device {block.device!r}"
                )
        for check in self.pre_check:
            if check.device not in names:
                offenders.append(
                    f"pre_check {check.check_id!r} "
                    f"references unknown device {check.device!r}"
                )
        for check in self.post_check:
            if check.device not in names:
                offenders.append(
                    f"post_check {check.check_id!r} "
                    f"references unknown device {check.device!r}"
                )

        if offenders:
            raise ValueError(
                "TCF FK violation:\n  - "
                + "\n  - ".join(offenders)
                + f"\n  known devices: {sorted(names)}"
            )
        return self

    @model_validator(mode="after")
    def _check_required_tests_exist(self) -> "CabTcf":
        """Every test_id in required_tests / optional_tests must exist
        in the tvt list. Prevents pass-criteria from referencing
        non-existent tests."""
        tvt_ids = {row.test_id for row in self.tvt}
        missing_required = [t for t in self.required_tests if t not in tvt_ids]
        missing_optional = [t for t in self.optional_tests if t not in tvt_ids]

        problems: list[str] = []
        if missing_required:
            problems.append(
                f"required_tests references unknown test_ids: "
                f"{missing_required}"
            )
        if missing_optional:
            problems.append(
                f"optional_tests references unknown test_ids: "
                f"{missing_optional}"
            )
        if problems:
            raise ValueError(
                "TCF test_id reference error:\n  - "
                + "\n  - ".join(problems)
                + f"\n  known test_ids: {sorted(tvt_ids)}"
            )
        return self


# ---------------------------------------------------------------------------
# Convenience constructor for new TCFs
# ---------------------------------------------------------------------------


def new_tcf(
    *,
    change_id: str,
    title: str,
    intent_type: str,
    devices: list[Device] | list[dict],
    created_by: str = "ops-analyze",
    risk_class: str = "medium",
    **intent_extras: Any,
) -> CabTcf:
    """Build a minimal CabTcf for a fresh change. Sim uses this as
    the starting point and then populates implementation / rollback /
    post_check / tvt lists.

    Devices may be passed as ``Device`` instances or plain dicts;
    Pydantic coerces.
    """
    return CabTcf(
        change_id=change_id,
        title=title,
        created_by=created_by,
        created_at=datetime.now(UTC),
        risk_class=risk_class,
        intent=Intent(type=intent_type, **intent_extras),
        devices=[
            d if isinstance(d, Device) else Device(**d) for d in devices
        ],
    )
