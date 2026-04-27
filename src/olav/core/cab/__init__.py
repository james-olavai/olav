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

from .tcf_args import tcf_to_r88_args, tcf_to_r89_args, tcf_to_r90_args
from .tcf_diff import (
    SilentOverride,
    TcfDiffResult,
    TvtDiff,
    tcf_diff_spec_vs_lab,
)
from .tcf_io import tcf_emit, tcf_load
from .tcf_schema import (
    CabTcf,
    CliBlock,
    Device,
    ExecutionRecord,
    Intent,
    JournalEntry,
    PostCheck,
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
    "TcfDiffResult",
    "TvtDiff",
    "TvtRow",
    "tcf_diff_spec_vs_lab",
    "tcf_emit",
    "tcf_load",
    "tcf_to_r88_args",
    "tcf_to_r89_args",
    "tcf_to_r90_args",
]
