"""Guard: shared metadata files between root `.olav/workspace/ops/`
and packaged `olav-netops/.olav/workspace/ops/` must stay byte-identical.

ADR-0002 / R77 post-audit decision: metadata (SKILL.md, AGENT.md,
MANIFEST.yaml, prompts/, config/*.yaml) is the skill contract — every
consumer must agree. Tool source code (`tools/*.py`) intentionally
diverges between the two copies while function signatures evolve
independently for the two test suites; the R77 follow-up round will
converge those implementations via shared Python modules in
``olav_netops.*``.

This guard catches accidental metadata drift (e.g. rename a sub-agent
in root SKILL.md but forget to update the olav-netops copy); not all
the deliberate tool-source divergence.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT_OPS = REPO / ".olav" / "workspace" / "ops"
NETOPS_OPS = REPO / "olav-netops" / ".olav" / "workspace" / "ops"

# Files that legitimately exist on only one side. Extend with care +
# one-line justification. An entry here is a waiver — prefer syncing
# over adding to this list.
ALLOWED_ONLY_IN_NETOPS = {
    "devops/prompts",        # devops sub-agent prompt bundle; not used by root dev loop
    "devops/references",     # ditto — reference docs shipped with wheel only
}
ALLOWED_ONLY_IN_ROOT: set[str] = set()


# Files covered by the drift check. Tool source code (tools/**.py) is
# intentionally excluded — signatures evolve independently between root
# and olav-netops pending R78 convergence work.
_TRACKED_SUFFIXES = {".md", ".yaml", ".yml"}
_EXCLUDED_DIRS = {"tools", "__pycache__"}


def _collect_files(root: Path) -> set[Path]:
    out: set[Path] = set()
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _EXCLUDED_DIRS for part in p.parts):
            continue
        if p.suffix not in _TRACKED_SUFFIXES:
            continue
        out.add(p.relative_to(root))
    return out


def _is_waived(rel: Path, waivers: set[str]) -> bool:
    return any(str(rel).startswith(w.rstrip("/") + "/") or str(rel) == w for w in waivers)


def test_root_and_netops_ops_workspaces_match():
    if not ROOT_OPS.exists() or not NETOPS_OPS.exists():
        # Either side missing means the repo isn't in the expected
        # monorepo layout — the SSOT test only makes sense when both
        # copies exist on the same disk.
        return

    root_files = _collect_files(ROOT_OPS)
    netops_files = _collect_files(NETOPS_OPS)

    only_root = {
        p for p in (root_files - netops_files)
        if not _is_waived(p, ALLOWED_ONLY_IN_ROOT)
    }
    only_netops = {
        p for p in (netops_files - root_files)
        if not _is_waived(p, ALLOWED_ONLY_IN_NETOPS)
    }
    assert not only_root, (
        "Files present in root .olav/workspace/ops/ but missing in "
        "olav-netops/.olav/workspace/ops/ (add to ALLOWED_ONLY_IN_ROOT "
        "or sync): "
        + ", ".join(sorted(str(p) for p in only_root))
    )
    assert not only_netops, (
        "Files present in olav-netops/.olav/workspace/ops/ but missing "
        "in root .olav/workspace/ops/ (add to ALLOWED_ONLY_IN_NETOPS or "
        "sync): "
        + ", ".join(sorted(str(p) for p in only_netops))
    )

    # Byte-compare every shared file.
    shared = root_files & netops_files
    divergent: list[str] = []
    for rel in sorted(shared):
        a = (ROOT_OPS / rel).read_bytes()
        b = (NETOPS_OPS / rel).read_bytes()
        if a != b:
            divergent.append(str(rel))
    assert not divergent, (
        "Content divergence between root and olav-netops ops/ — these "
        "files must be byte-identical (either location may be edited; "
        "sync the other before committing):\n  "
        + "\n  ".join(divergent)
    )
