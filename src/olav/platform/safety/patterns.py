"""Shared dangerous-command patterns used by safety middleware and run_shell tool.

Single source of truth — import from here, never duplicate.
"""
from __future__ import annotations

# Shell commands that can cause irreversible data loss or system damage.
# Used by:
#   - OLAVSafetyMiddleware (src/olav/plugins/middleware/safety.py) — triggers HITL interrupt
#   - run_shell tool (.olav/workspace/core/remote/tools/run_shell.py) — hard-blocks execution
DANGEROUS_EXEC_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "rm -fr",
    "mkfs",
    "dd if=",
    "wipefs",
    "> /dev/",
    ":(){ :",         # fork bomb
    "chmod -R 777 /",
    "shred ",
    "fdisk",
    "parted",
)

# Absolute path prefixes that agents must never write to.
# Used by OLAVSafetyMiddleware write_file check.
BLOCKED_WRITE_PREFIXES: tuple[str, ...] = (
    "/etc/",
    "/usr/",
    "/bin/",
    "/sbin/",
    "/boot/",
    "/sys/",
    "/proc/",
    "/root/",
)
