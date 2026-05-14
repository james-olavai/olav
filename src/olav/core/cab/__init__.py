"""R90 — TCF (Test Case File) module.

Structured sim↔lab change contract. See ``dev_docs/65`` for design.

**2026-05-14 cleanup**: the legacy sim Python pipeline (``sim/`` package,
``tcf_writer``, ``tcf_sim``, ``draft_fill``, ``schemas``, plus helpers
``intf_picker`` / ``lab_subnet_pool`` / ``generic_intent_handler`` /
``semantic_review`` / ``pre_check_runner``) was removed; sim is being
rebuilt as a Batfish-backed sub-agent per ``dev_docs/77 §2``.  The
TCF contract layer below (``tcf_schema``, ``tcf_io``, ``tcf_lab``,
``tcf_validate``, ``tcf_args``, ``tcf_diff``, ``postcheck_translate``,
``prod_cli``, ``intent_registry``) is kept because the lab sub-agent
still consumes ``spec.tcf.yaml``.  Lab redesign per ``dev_docs/78`` is
deferred; until then lab continues to work against the legacy TCF
spec format produced by external sources / hand-written specs.

Public API:
    * ``CabTcf`` — top-level Pydantic model for a CAB change record
    * ``tcf_load(path)`` — read + parse + validate from disk
    * ``tcf_emit(tcf, path)`` — write a CabTcf to disk (atomic)

Subordinate models (re-exported for typing):
    * Intent, Device, CliBlock, PostCheck, TvtRow,
      JournalEntry, ExecutionRecord
"""

from .prod_cli import (
    derive_prod_cli_from_tcf,
    generate_ios_ebgp_config,
    generate_ios_ebgp_rollback,
    generate_junos_ebgp_config,
    generate_junos_ebgp_rollback,
)
from .tcf_args import (
    tcf_to_clab_topology_args,
    tcf_to_prod_cli_args,
    tcf_to_r88_args,
    tcf_to_r89_args,
    tcf_to_r90_args,
    tcf_to_srl_render_args,
)
from .tcf_diff import (
    SilentOverride,
    TcfDiffResult,
    TvtDiff,
    tcf_diff_spec_vs_lab,
)
from .tcf_io import tcf_emit, tcf_load
from .tcf_lab import tcf_load_for_lab, tcf_record_lab_run
from .tcf_validate import validate_tcf_in_lab
from .tcf_schema import (
    CabTcf,
    CliBlock,
    Device,
    ExecutionRecord,
    Intent,
    JournalEntry,
    PostCheck,
    StepVerdict,
    TvtRow,
)

__all__ = [
    "CabTcf",
    "CliBlock",
    "Device",
    "ExecutionRecord",
    "Intent",
    "JournalEntry",
    "PostCheck",
    "SilentOverride",
    "StepVerdict",
    "TcfDiffResult",
    "TvtDiff",
    "TvtRow",
    "derive_prod_cli_from_tcf",
    "generate_ios_ebgp_config",
    "generate_ios_ebgp_rollback",
    "generate_junos_ebgp_config",
    "generate_junos_ebgp_rollback",
    "tcf_diff_spec_vs_lab",
    "tcf_emit",
    "tcf_load",
    "tcf_load_for_lab",
    "tcf_record_lab_run",
    "validate_tcf_in_lab",
    "tcf_to_r88_args",
    "tcf_to_r89_args",
    "tcf_to_r90_args",
    "tcf_to_clab_topology_args",
    "tcf_to_srl_render_args",
    "tcf_to_prod_cli_args",
]
