#!/usr/bin/env python3
"""workspace_drift.py — N-way drift reporter across all workspace copies.

Supersedes the ops-only ``sync_netops_workspace.py`` for *diagnosis*.
This tool is **read-only by default** — it never writes unless you pass
``--apply`` together with an explicit ``--direction`` (see SAFETY below).

Why this exists
---------------
OLAV's workspace content currently lives in up to three places per
domain, and ISSUE-ARCH-AUDIT-WORKSPACE-DUAL-COPY-DEBT found they have
**drifted** (e.g. core AGENT.md is v4.0.0 in the runtime copy but v3.2.0
in the wheel source).  Before consolidating to a single
source-of-truth, we need an authoritative, repeatable picture of *which
files differ between which copies*.

Copy roles (target steady-state model)
---------------------------------------
| Domain | Authoritative source (edit + commit here)        | Generated mirrors (git-ignored)          |
|--------|---------------------------------------------------|------------------------------------------|
| core   | src/olav/data/workspace/core                      | .olav/workspace/core                     |
| audit  | olav-netops/.olav/workspace/audit  (netops home)  | .olav/workspace/audit  +  src/olav/data/workspace/audit (wheel fallback) |
| netops | olav-netops/.olav/workspace/netops                | .olav/workspace/netops                   |
| devops | olav-netops/.olav/workspace/devops                | .olav/workspace/devops                   |
| ops    | olav-netops/.olav/workspace/ops                   | .olav/workspace/ops                      |

Determining "which copy is latest" (maintainer's rule): the copy that uses
the latest deepagents workflow (``rubric_middleware`` / ``enable_todo_list``)
is the current one.  By that rule the wheel ``src/olav/data/workspace/*``
copies are objectively stale (0 markers), and:
  * **audit** — authoritative = the netops bundle (clean latest: explorer,
    no dead curator). runtime carries pre-consolidation leftovers
    (curator/, prompts/orchestrator.md, prompts/system.md) to be dropped.
  * **core** — latest content currently sits in the RUNTIME copy (v4.0.0);
    the one-time fix promotes runtime → wheel source, after which the wheel
    source is authoritative.

NOTE — content reconciliation + release blessing is gated on the new e2e
suite passing (maintainer directive).  Until then this tool only *reports*
the drift.  See dev_docs/91. WORKSPACE_SSOT_CONSOLIDATION.md.

SAFETY
------
* Default / ``--check`` / ``--dry-run``: read-only.  Exit 2 on drift
  (CI-friendly).
* ``--apply`` requires ``--direction {to-runtime,to-source}`` AND
  ``--domain <name>`` — there is no default write direction, precisely
  because the authoritative direction differs per domain and is being
  reconciled.  Picking the wrong direction would overwrite live content
  with stale content, so we force the operator to be explicit.

Metadata scope
--------------
Only ``.md`` / ``.yaml`` / ``.yml`` files are compared (the skill
contract).  ``tools/`` and ``scripts/`` Python sources are excluded —
they evolve independently per the SSOT governance test.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_METADATA_SUFFIXES = {".md", ".yaml", ".yml"}
_EXCLUDED_DIRS = {"tools", "scripts", "__pycache__", ".pytest_cache", ".ruff_cache"}

# Sub-agents that live under a domain's namespace but are shipped by a
# DIFFERENT delivery unit, so the domain's source will never contain them.
# `netops/lab` is routed as a netops sub-agent and ships with olav-ent
# (dev_docs/112); `olav agent install olav-ent` puts it in the runtime mirror.
# Reporting it as drift would train everyone to ignore this gate — which is
# the one thing a drift gate cannot afford.
_FOREIGN_SUBAGENTS = {"netops": {"lab"}}


@dataclass(frozen=True)
class Domain:
    name: str
    source: Path          # authoritative (target steady-state)
    runtime: Path         # generated runtime mirror
    extra_mirrors: tuple[Path, ...] = ()  # e.g. olav-netops audit bundle


DOMAINS: list[Domain] = [
    Domain(
        name="core",
        source=REPO / "src/olav/data/workspace/core",
        runtime=REPO / ".olav/workspace/core",
    ),
    Domain(
        # audit's home is the netops bundle (shipped via `olav skill install`).
        # It is the clean latest copy: uses the current deepagents workflow
        # (rubric_middleware), has the `explorer` sub-agent, and dropped the
        # dead `curator` (removed 2026-05-27, see audit/AGENT.md). The wheel
        # copy under src/olav/data/workspace/audit is a stale 0.17-era
        # init-time fallback, regenerated FROM this source.
        name="audit",
        source=REPO / "olav-netops/.olav/workspace/audit",
        runtime=REPO / ".olav/workspace/audit",
        extra_mirrors=(
            REPO / "src/olav/data/workspace/audit",
            # PyPI wheel bundle (0.22.0): `olav skill install olav-netops`
            # deploys from this copy when installed via pip (no source tree).
            REPO / "olav-netops/src/olav_netops/data/skillpack/.olav/workspace/audit",
        ),
    ),
    Domain(
        name="netops",
        source=REPO / "olav-netops/.olav/workspace/netops",
        runtime=REPO / ".olav/workspace/netops",
        extra_mirrors=(
            # PyPI wheel bundle (0.22.0) — see audit note above.
            REPO / "olav-netops/src/olav_netops/data/skillpack/.olav/workspace/netops",
        ),
    ),
    Domain(
        name="devops",
        source=REPO / "olav-netops/.olav/workspace/devops",
        runtime=REPO / ".olav/workspace/devops",
    ),
    Domain(
        name="ops",
        source=REPO / "olav-netops/.olav/workspace/ops",
        runtime=REPO / ".olav/workspace/ops",
    ),
]


def _metadata_files(root: Path, domain: str | None = None) -> set[Path]:
    """Relative paths of all metadata files under *root* (excluded dirs skipped).

    ``domain`` lets a sub-agent shipped by another delivery unit be left out —
    see ``_FOREIGN_SUBAGENTS``.
    """
    out: set[Path] = set()
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] in _FOREIGN_SUBAGENTS.get(domain, ()):
            continue
        if p.suffix not in _METADATA_SUFFIXES:
            continue
        out.add(rel)
    return out


@dataclass
class PairDrift:
    label_a: str
    label_b: str
    only_a: list[Path]
    only_b: list[Path]
    differ: list[Path]

    @property
    def total(self) -> int:
        return len(self.only_a) + len(self.only_b) + len(self.differ)


# Deliberately ABSENT from wheel-bundle mirrors (data/skillpack): live lab
# credentials/inventory must never ship in a public wheel — only the
# .example templates do. The runtime mirror still carries them (dev box
# collection needs real creds), so the exemption applies to bundle
# comparisons only.
_WHEEL_BUNDLE_EXEMPT: set[Path] = {
    Path("collector/config/nornir/defaults.yaml"),
    Path("collector/config/nornir/hosts.yaml"),
}


def _compare(
    a: Path, label_a: str, b: Path, label_b: str, exempt: set[Path] = frozenset(),
    domain: str | None = None,
) -> PairDrift:
    fa = _metadata_files(a, domain) - exempt
    fb = _metadata_files(b, domain) - exempt
    only_a = sorted(fa - fb)
    only_b = sorted(fb - fa)
    differ = sorted(
        rel for rel in (fa & fb) if (a / rel).read_bytes() != (b / rel).read_bytes()
    )
    return PairDrift(label_a, label_b, only_a, only_b, differ)


def _print_pair(pd: PairDrift, rel_to: Path) -> None:
    if pd.total == 0:
        print(f"    {pd.label_a}  ==  {pd.label_b}   (no drift)")
        return
    print(f"    {pd.label_a}  ~~  {pd.label_b}   ({pd.total} drifted)")
    for rel in pd.differ:
        print(f"      DIFFER     {rel}")
    for rel in pd.only_a:
        print(f"      only<{pd.label_a}> {rel}")
    for rel in pd.only_b:
        print(f"      only<{pd.label_b}> {rel}")


def report() -> int:
    """Print the full N-way drift report. Exit 2 if any drift found."""
    any_drift = False
    for dom in DOMAINS:
        print(f"\n=== domain: {dom.name} ===")
        print(f"    source : {dom.source.relative_to(REPO)}"
              f"  ({'exists' if dom.source.exists() else 'MISSING'})")
        print(f"    runtime: {dom.runtime.relative_to(REPO)}"
              f"  ({'exists' if dom.runtime.exists() else 'MISSING'})")
        for m in dom.extra_mirrors:
            print(f"    bundle : {m.relative_to(REPO)}"
                  f"  ({'exists' if m.exists() else 'MISSING'})")

        pairs: list[PairDrift] = []
        if dom.source.exists() and dom.runtime.exists():
            pairs.append(_compare(dom.source, "source", dom.runtime, "runtime",
                                  domain=dom.name))
        for m in dom.extra_mirrors:
            if dom.source.exists() and m.exists():
                exempt = _WHEEL_BUNDLE_EXEMPT if "skillpack" in m.parts else frozenset()
                pairs.append(_compare(dom.source, "source", m, "bundle",
                                      exempt=exempt, domain=dom.name))
        for pd in pairs:
            _print_pair(pd, REPO)
            if pd.total:
                any_drift = True

    print("\n" + "=" * 60)
    print("  DRIFT FOUND" if any_drift else "  ALL COPIES IN SYNC")
    print("=" * 60)
    return 2 if any_drift else 0


def apply_sync(domain_name: str, direction: str) -> int:
    """Explicit, guarded one-direction sync of metadata files.

    direction == 'to-runtime': source -> runtime  (steady state)
    direction == 'to-source':  runtime -> source  (one-time promotion)
    """
    dom = next((d for d in DOMAINS if d.name == domain_name), None)
    if dom is None:
        print(f"ERROR: unknown domain '{domain_name}'", file=sys.stderr)
        return 1
    if direction == "to-runtime":
        src, dst = dom.source, dom.runtime
    elif direction == "to-source":
        src, dst = dom.runtime, dom.source
    else:  # pragma: no cover - argparse choices guard this
        print(f"ERROR: bad direction '{direction}'", file=sys.stderr)
        return 1
    if not src.exists():
        print(f"ERROR: source path missing: {src}", file=sys.stderr)
        return 1

    written = 0
    for rel in sorted(_metadata_files(src)):
        s, d = src / rel, dst / rel
        if d.exists() and s.read_bytes() == d.read_bytes():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        print(f"  wrote {dst.relative_to(REPO)}/{rel}")
        written += 1
    print(f"\nSynced {written} file(s): {src.relative_to(REPO)} -> {dst.relative_to(REPO)}")
    print("NOTE: extra_mirrors (e.g. olav-netops audit bundle) are NOT auto-written; "
          "run per target if needed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report (and, with --apply, reconcile) workspace metadata drift.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true",
                        help="CI mode: exit 2 if any drift (read-only). Default behaviour.")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes. Requires --direction and --domain.")
    parser.add_argument("--direction", choices=["to-runtime", "to-source"],
                        help="Sync direction (only with --apply).")
    parser.add_argument("--domain", choices=[d.name for d in DOMAINS],
                        help="Restrict --apply to one domain (required with --apply).")
    args = parser.parse_args(argv)

    if args.apply:
        if not args.direction or not args.domain:
            parser.error("--apply requires both --direction and --domain "
                         "(no default write direction — see SAFETY in module docstring).")
        return apply_sync(args.domain, args.direction)

    return report()


if __name__ == "__main__":
    sys.exit(main())
