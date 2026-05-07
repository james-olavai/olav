"""R90 — TCF (Test Case File) module.

Structured sim↔lab change contract. See ``dev_docs/65`` for design.

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
from .semantic_review import review_cli_pair, review_paired_blocks
from .tcf_args import tcf_to_r88_args, tcf_to_r89_args, tcf_to_r90_args
from .tcf_diff import (
    SilentOverride,
    TcfDiffResult,
    TvtDiff,
    tcf_diff_spec_vs_lab,
)
from .tcf_io import tcf_emit, tcf_load
from .tcf_lab import tcf_load_for_lab, tcf_record_lab_run
from .tcf_patch import tcf_patch_block
from .tcf_review import review_prod_cli
from .tcf_validate import validate_tcf_in_lab
from .tcf_schema import (
    CabTcf,
    CliBlock,
    Device,
    ExecutionRecord,
    Intent,
    JournalEntry,
    PostCheck,
    ProdReviewFinding,
    StepVerdict,
    TvtRow,
)
from .tcf_sim import tcf_emit_from_sim

__all__ = [
    "CabTcf",
    "CliBlock",
    "Device",
    "ExecutionRecord",
    "Intent",
    "JournalEntry",
    "PostCheck",
    "ProdReviewFinding",
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
    "review_cli_pair",
    "review_paired_blocks",
    "review_prod_cli",
    "tcf_diff_spec_vs_lab",
    "tcf_emit",
    "tcf_emit_from_sim",
    "tcf_load",
    "tcf_load_for_lab",
    "tcf_patch_block",
    "tcf_record_lab_run",
    "validate_tcf_in_lab",
    "tcf_to_r88_args",
    "tcf_to_r89_args",
    "tcf_to_r90_args",
]
