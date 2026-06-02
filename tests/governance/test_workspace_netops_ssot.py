"""Guard: shared metadata files between root `.olav/workspace/netops/`
and packaged `olav-netops/.olav/workspace/netops/` must stay byte-identical.

Mirrors test_workspace_ops_ssot.py for the netops/ domain — the same
ADR-0002 SSOT principle applies: metadata (SKILL.md, AGENT.md,
MANIFEST.yaml, prompts/, config/*.yaml) is the skill contract and must
agree between the dev mirror and the packaged copy shipped with the wheel.

Tool source code (`tools/*.py`, `scripts/*.py`) is intentionally excluded
from this byte-compare because tool implementations can evolve independently
between the two copies pending the R78 convergence work.

Workflow: edit whichever copy is convenient, then sync the other before
committing. The governance test will tell you exactly which files diverged.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT_NETOPS = REPO / ".olav" / "workspace" / "netops"
PKG_NETOPS = REPO / "olav-netops" / ".olav" / "workspace" / "netops"

# Files that legitimately exist on only one side. Add entries with a
# one-line justification. An entry here is a waiver — prefer syncing
# over growing this list.
ALLOWED_ONLY_IN_PKG: set[str] = {
    "analyzer/references/ROUTING_EXPERT_GUIDE.md",  # reference doc shipped with wheel only
}
ALLOWED_ONLY_IN_ROOT: set[str] = set()

_TRACKED_SUFFIXES = {".md", ".yaml", ".yml"}
_EXCLUDED_DIRS = {"tools", "scripts", "__pycache__"}


def _collect_files(root: Path) -> set[Path]:
    out: set[Path] = set()
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _EXCLUDED_DIRS for part in p.relative_to(root).parts):
            continue
        if p.suffix not in _TRACKED_SUFFIXES:
            continue
        out.add(p.relative_to(root))
    return out


def _is_waived(rel: Path, waivers: set[str]) -> bool:
    s = str(rel)
    return any(s == w or s.startswith(w.rstrip("/") + "/") for w in waivers)


def test_root_and_netops_netops_workspaces_match():
    """Both workspace/netops/ copies must have the same metadata files
    with identical content (tools/ and scripts/ are excluded).
    """
    if not ROOT_NETOPS.exists() or not PKG_NETOPS.exists():
        # Not in full monorepo layout — skip rather than fail.
        return

    root_files = _collect_files(ROOT_NETOPS)
    pkg_files = _collect_files(PKG_NETOPS)

    only_root = {p for p in (root_files - pkg_files) if not _is_waived(p, ALLOWED_ONLY_IN_ROOT)}
    only_pkg = {p for p in (pkg_files - root_files) if not _is_waived(p, ALLOWED_ONLY_IN_PKG)}

    assert not only_root, (
        "Metadata files present in root .olav/workspace/netops/ but missing in "
        "olav-netops/.olav/workspace/netops/. Sync or add to ALLOWED_ONLY_IN_ROOT:\n  "
        + "\n  ".join(sorted(str(p) for p in only_root))
    )
    assert not only_pkg, (
        "Metadata files present in olav-netops/.olav/workspace/netops/ but missing "
        "in root .olav/workspace/netops/. Sync or add to ALLOWED_ONLY_IN_PKG:\n  "
        + "\n  ".join(sorted(str(p) for p in only_pkg))
    )

    shared = root_files & pkg_files
    divergent: list[str] = []
    for rel in sorted(shared):
        if (ROOT_NETOPS / rel).read_bytes() != (PKG_NETOPS / rel).read_bytes():
            divergent.append(str(rel))

    assert not divergent, (
        "Content divergence between root and olav-netops netops/ workspace — "
        "these files must be byte-identical:\n  "
        + "\n  ".join(divergent)
    )
