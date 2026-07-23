#!/usr/bin/env python3
"""publish_github_mirrors.py — repeatable GitHub publication for OLAV.

Codifies the two publication flows first executed manually for v0.22.0
(dev_docs/99 §7.6 follow-up). gitea stays the unfiltered internal source
of truth; GitHub carries two curated views:

  netops   Standalone olav-netops repo (github.com/james-olavai/olav-netops).
           Snapshot of the monorepo subtree: git-tracked files only, live
           nornir credentials/inventory stripped (.example templates ship),
           one commit per release on top of the previous snapshot.

  mirror   Public monorepo (github.com/james-olavai/olav). Full history
           re-filtered through git-filter-repo: credential file paths
           removed, token/password literals redacted, AND the enterprise /
           private delivery units stripped (olav-ent, olav-presales, olav-post —
           see _ENTERPRISE_UNIT_PATHS). filter-repo is deterministic, so
           re-running over extended history keeps already-published SHAs stable
           → pushes stay fast-forward.

  collector  Standalone olav-collector repo
           (github.com/james-olavai/olav-collector). The source dir is
           NOT tracked in the monorepo (manifest: git ignore, standalone
           unit) — export is a raw directory copy with an exclude list
           (live credentials.env, output/ collection artifacts, vendored
           wheels/). The scan additionally reads the local
           credentials.env VALUES and refuses to publish anything
           containing a non-trivial one.

Usage:
    python scripts/publish_github_mirrors.py netops            # dry-run
    python scripts/publish_github_mirrors.py netops --push
    python scripts/publish_github_mirrors.py mirror            # dry-run
    python scripts/publish_github_mirrors.py mirror --push
    python scripts/publish_github_mirrors.py collector [--push]

Safety:
  * Default is dry-run — nothing leaves the machine without --push.
  * Both flows hard-fail if the secret scan finds a hit in what would
    be published.
  * Literal secret patterns (e.g. a leaked password string) must NOT
    live in this file — the mirror would then republish them. Built-in
    rules are shape-regexes only; literals belong in the untracked
    local rules file (see _EXTRA_RULES_PATH), format: one
    `pattern==>replacement` per line, `regex:` prefix supported.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workspace_drift import _WHEEL_BUNDLE_EXEMPT  # single source for cred paths

REPO = Path(__file__).resolve().parents[1]

NETOPS_REMOTE = "https://github.com/james-olavai/olav-netops.git"
MIRROR_REMOTE = "https://github.com/james-olavai/olav.git"
COLLECTOR_REMOTE = "https://github.com/james-olavai/olav-collector.git"
COLLECTOR_DIR = REPO / "olav-collector"

# Never exported from olav-collector (top-level names; '=' catches pip
# redirect accidents like a stray file literally named '=4.13.2').
_COLLECTOR_EXCLUDES = {"credentials.env", "output", "wheels", ".git"}
_COLLECTOR_EXCLUDE_ANYWHERE = {"__pycache__", ".pytest_cache"}

# Untracked local file for literal scrub rules (never committed — .olav/
# is whitelist-ignored). Required for `mirror`; also feeds the secret scan.
_EXTRA_RULES_PATH = REPO / ".olav" / "config" / "github-mirror-scrub.txt"

# Shape-only patterns (no secret literals) — used by both the scrub and
# the pre-publish scan.
_TOKEN_REGEX = r"olav_[0-9a-f]{64}"
_SCAN_PATTERNS = [
    _TOKEN_REGEX,
    r"sk-[A-Za-z0-9]{24,}",
    r"BEGIN [A-Z ]*PRIVATE KEY",
]

# Live nornir credential/inventory files, as paths relative to a workspace
# root — derived from the same list the drift gate exempts in wheel bundles.
_CRED_WORKSPACE_RELPATHS = sorted(str(p) for p in _WHEEL_BUNDLE_EXEMPT)

# All path variants these files have occupied across monorepo history
# (pre-rename locations included). Paths are not secrets — safe to track.
_HISTORICAL_CRED_PATHS = [
    "claude-code-migration/config/nornir/defaults.yaml",
    "claude-code-migration/config/nornir/hosts.yaml",
    ".olav/config/nornir/defaults.yaml",
    ".olav/config/nornir/hosts.yaml",
    "olav-netops/.olav/workspace/netops/collect/config/nornir/defaults.yaml",
    "olav-netops/.olav/workspace/netops/collect/config/nornir/hosts.yaml",
    "olav-netops/.olav/workspace/netops/collector/config/nornir/defaults.yaml",
    "olav-netops/.olav/workspace/netops/collector/config/nornir/hosts.yaml",
    "olav-netops/src/olav_netops/data/skillpack/.olav/workspace/netops/collector/config/nornir/defaults.yaml",
    "olav-netops/src/olav_netops/data/skillpack/.olav/workspace/netops/collector/config/nornir/hosts.yaml",
]

# Enterprise / private delivery units — NEVER published to the public monorepo
# mirror. gitea (internal) keeps the full source; the public GitHub mirror strips
# these dir prefixes from all history via git-filter-repo --invert-paths. olav-ent
# is proprietary; olav-presales is the (proprietary) enterprise presales domain
# bundled with olav-ent; olav-post is local-only (CLAUDE.md). Trailing slash =
# directory prefix, so everything under them is removed.
_ENTERPRISE_UNIT_PATHS = [
    "olav-ent/",
    "olav-presales/",
    "olav-post/",
    # Enterprise grounding corpus (curated selection expertise — dev_docs/104 §9
    # commercial layer). Lives under the shared olav_kb/ dir, so it needs an
    # explicit prefix to be stripped from the public mirror. (presales dev_docs
    # stay public per the enterprise-positioning decision 5 — not stripped.)
    "olav_kb/presales/",
]

_NETOPS_GITIGNORE = """\
__pycache__/
*.pyc
dist/
.venv/
uv.lock
exports/
# Live lab credentials/inventory — use the .example templates
.olav/workspace/netops/collector/config/nornir/defaults.yaml
.olav/workspace/netops/collector/config/nornir/hosts.yaml
"""


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{proc.stderr}")
    return proc.stdout


def _load_extra_literals() -> list[str]:
    """Plain-literal patterns from the local rules file, for scanning."""
    if not _EXTRA_RULES_PATH.exists():
        return []
    out = []
    for line in _EXTRA_RULES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==>" not in line:
            continue
        pattern = line.split("==>", 1)[0]
        out.append(pattern.removeprefix("regex:"))
    return out


def _secret_scan(root: Path, extra_patterns: list[str] | None = None) -> list[str]:
    """Scan a tree for secret patterns. Returns offending 'path: pattern' hits."""
    patterns = [
        re.compile(p.encode())
        for p in _SCAN_PATTERNS + _load_extra_literals() + (extra_patterns or [])
    ]
    hits = []
    for f in root.rglob("*"):
        if not f.is_file() or ".git" in f.parts:
            continue
        try:
            data = f.read_bytes()
        except OSError:
            continue
        for pat in patterns:
            if pat.search(data):
                hits.append(f"{f.relative_to(root)}: /{pat.pattern.decode()}/")
    return hits


# ── netops: standalone snapshot repo ─────────────────────────────────────────


def publish_netops(push: bool) -> int:
    version = tomllib.loads(
        (REPO / "olav-netops" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    print(f"olav-netops version: {version}")

    with tempfile.TemporaryDirectory(prefix="netops-pub-") as tmp:
        tmp = Path(tmp)
        clone = tmp / "repo"
        print(f"cloning {NETOPS_REMOTE} …")
        _run(["git", "clone", "-q", NETOPS_REMOTE, str(clone)])

        # Replace tracked content with a fresh tracked-files-only export.
        for entry in clone.iterdir():
            if entry.name != ".git":
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
        export = tmp / "export.tar"
        with export.open("wb") as fh:
            subprocess.run(
                ["git", "archive", "HEAD", "--", "olav-netops/"],
                cwd=REPO, stdout=fh, check=True,
            )
        _run(["tar", "-xf", str(export), "-C", str(clone), "--strip-components=1"])

        # Strip live credential/inventory files; ship .example templates only.
        for rel in _CRED_WORKSPACE_RELPATHS:
            target = clone / ".olav" / "workspace" / "netops" / rel
            if target.exists():
                target.unlink()
                print(f"stripped: {target.relative_to(clone)}")
        (clone / ".gitignore").write_text(_NETOPS_GITIGNORE, encoding="utf-8")

        hits = _secret_scan(clone)
        if hits:
            print("SECRET SCAN FAILED — refusing to publish:")
            print("\n".join(f"  {h}" for h in hits))
            return 2
        print("secret scan: clean")

        _run(["git", "add", "-A"], cwd=clone)
        if not _run(["git", "status", "--porcelain"], cwd=clone).strip():
            print("no changes vs remote — already up to date")
            return 0
        _run(
            ["git", "-c", "user.name=OLAV Team", "-c", "user.email=olav@olavai.com",
             "commit", "-q", "-m",
             f"olav-netops v{version} — snapshot from monorepo\n\n"
             f"Tracked-files export; live nornir credentials/inventory excluded\n"
             f"(use the .example templates). See scripts/publish_github_mirrors.py.\n"],
            cwd=clone,
        )
        tag = f"v{version}"
        existing = _run(["git", "tag", "-l", tag], cwd=clone).strip()
        _run(["git", "tag", "-f" if existing else "-a", tag, "-m", tag] if not existing
             else ["git", "tag", "-f", tag], cwd=clone)
        print(f"commit: {_run(['git', 'log', '--oneline', '-1'], cwd=clone).strip()}")

        if not push:
            print("dry-run — skipping push (use --push to publish)")
            return 0
        _run(["git", "push", "origin", "main"], cwd=clone)
        _run(["git", "push", "-f", "origin", tag], cwd=clone)
        print(f"pushed main + {tag} → {NETOPS_REMOTE}")
    return 0


# ── collector: standalone snapshot repo (untracked source dir) ──────────────


def _collector_secret_values() -> list[str]:
    """Secret-shaped VALUES from the local credentials.env — patterns whose
    appearance in published content would leak an actual secret.

    Skips values that carry negligible secret entropy AND collide with
    ordinary text, because redacting them would corrupt legitimate content
    (sample data, vendor tokens) for no security gain:
      * pure digits / ≤3 chars  — e.g. port 22
      * a lowercase word ≤6 chars — e.g. a default username 'cisco' that is
        indistinguishable from the vendor name throughout the codebase
    A real password like '<redacted-lab-password>' (has digits) is still flagged. The
    live credentials.env file itself is never exported regardless.
    """
    creds = COLLECTOR_DIR / "credentials.env"
    if not creds.exists():
        return []
    out = []
    for line in creds.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) <= 3 or value.isdigit():
            continue
        if len(value) <= 6 and value.isalpha() and value.islower():
            continue
        out.append(re.escape(value))
    return out


def publish_collector(push: bool) -> int:
    version = tomllib.loads(
        (COLLECTOR_DIR / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    print(f"olav-collector version: {version}")

    with tempfile.TemporaryDirectory(prefix="collector-pub-") as tmp:
        tmp = Path(tmp)
        clone = tmp / "repo"
        print(f"cloning {COLLECTOR_REMOTE} …")
        _run(["git", "clone", "-q", COLLECTOR_REMOTE, str(clone)])

        for entry in clone.iterdir():
            if entry.name != ".git":
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()

        def _ignore(dirpath: str, names: list[str]) -> set[str]:
            skip = set()
            for n in names:
                if n in _COLLECTOR_EXCLUDE_ANYWHERE or n.endswith(".pyc") or n.startswith("="):
                    skip.add(n)
                if Path(dirpath) == COLLECTOR_DIR and n in _COLLECTOR_EXCLUDES:
                    skip.add(n)
            return skip

        shutil.copytree(COLLECTOR_DIR, clone, ignore=_ignore, dirs_exist_ok=True)

        hits = _secret_scan(clone, extra_patterns=_collector_secret_values())
        if hits:
            print("SECRET SCAN FAILED — refusing to publish:")
            print("\n".join(f"  {h}" for h in hits))
            return 2
        print("secret scan: clean (incl. live credentials.env values)")

        # The export must be self-consistent: its own tests must pass.
        test_run = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q"],
            cwd=clone, capture_output=True, text=True,
        )
        if test_run.returncode != 0:
            print(f"EXPORT TESTS FAILED — refusing to publish:\n{test_run.stdout[-800:]}")
            return 2
        print(f"export tests: {test_run.stdout.strip().splitlines()[-1]}")

        _run(["git", "add", "-A"], cwd=clone)
        if not _run(["git", "status", "--porcelain"], cwd=clone).strip():
            print("no changes vs remote — already up to date")
            return 0
        _run(
            ["git", "-c", "user.name=OLAV Team", "-c", "user.email=olav@olavai.com",
             "commit", "-q", "-m",
             f"olav-collector v{version} — snapshot publication\n\n"
             f"Directory export from the dev machine (source is untracked in the\n"
             f"monorepo by design); live credentials, collection output, and\n"
             f"vendored wheels excluded. See scripts/publish_github_mirrors.py.\n"],
            cwd=clone,
        )
        tag = f"v{version}"
        _run(["git", "tag", "-f", tag], cwd=clone)
        print(f"commit: {_run(['git', 'log', '--oneline', '-1'], cwd=clone).strip()}")

        if not push:
            print("dry-run — skipping push (use --push to publish)")
            return 0
        _run(["git", "push", "origin", "main"], cwd=clone)
        _run(["git", "push", "-f", "origin", tag], cwd=clone)
        print(f"pushed main + {tag} → {COLLECTOR_REMOTE}")
    return 0


# ── mirror: filtered public monorepo ─────────────────────────────────────────


def publish_mirror(push: bool) -> int:
    if not _EXTRA_RULES_PATH.exists():
        print(f"ERROR: {_EXTRA_RULES_PATH} missing.\n"
              "It must hold the literal scrub rules (one `pattern==>replacement`\n"
              "per line) that cannot be committed to the repo. Recreate it from\n"
              "the secure note before mirroring.")
        return 2

    with tempfile.TemporaryDirectory(prefix="olav-mirror-") as tmp:
        tmp = Path(tmp)
        clone = tmp / "repo"
        print("fresh-cloning local repo …")
        _run(["git", "clone", "-q", f"file://{REPO}", str(clone)])

        rules = tmp / "rules.txt"
        rules.write_text(
            f"regex:{_TOKEN_REGEX}==>olav_<redacted-dev-token>\n"
            + _EXTRA_RULES_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        paths = tmp / "paths.txt"
        # Strip credential files AND enterprise/private delivery units from the
        # public mirror history (olav-ent / olav-presales / olav-post).
        paths.write_text(
            "\n".join(_HISTORICAL_CRED_PATHS + _ENTERPRISE_UNIT_PATHS) + "\n",
            encoding="utf-8",
        )

        print("running git-filter-repo …")
        _run([sys.executable, "-m", "git_filter_repo", "--force",
              "--invert-paths", "--paths-from-file", str(paths),
              "--replace-text", str(rules)], cwd=clone)

        # Verify: no scrubbed pattern survives anywhere in the rewritten history.
        for pat in [_TOKEN_REGEX] + _load_extra_literals():
            out = _run(["git", "log", "--all", "-G", pat, "--oneline"], cwd=clone, check=False)
            if out.strip():
                print(f"VERIFY FAILED — pattern /{pat}/ still present:\n{out[:400]}")
                return 2
        # Exact line-match — substring matching would false-positive on the
        # sibling .example files (…/defaults.yaml is a prefix of
        # …/defaults.yaml.example).
        namelog_lines = set(
            _run(["git", "log", "--all", "--format=", "--name-only"], cwd=clone).splitlines()
        )
        leaked = [p for p in _HISTORICAL_CRED_PATHS if p in namelog_lines]
        if leaked:
            print(f"VERIFY FAILED — credential paths still in history: {leaked}")
            return 2
        # Enterprise/private units must be fully gone from the public mirror.
        ent_leaked = sorted({ln for ln in namelog_lines
                             for pre in _ENTERPRISE_UNIT_PATHS if ln.startswith(pre)})
        if ent_leaked:
            print("VERIFY FAILED — enterprise-unit files still in mirror history: "
                  f"{ent_leaked[:10]} (+{max(0, len(ent_leaked) - 10)} more)")
            return 2
        head = _run(["git", "rev-parse", "HEAD"], cwd=clone).strip()
        print(f"scrub verified clean; filtered HEAD = {head[:12]}")

        if not push:
            print("dry-run — skipping push (use --push to publish)")
            return 0
        _run(["git", "remote", "add", "github", MIRROR_REMOTE], cwd=clone)
        # --force on main: filter-repo rewrites history, so a re-filter that
        # diverges from a stale remote (e.g. a prior release that never fully
        # pushed) is not fast-forward. The scrub verification above gates this
        # — the filtered tree is confirmed credential-clean before any push.
        _run(["git", "push", "github", "main", "--force"], cwd=clone)
        _run(["git", "push", "github", "--tags", "--force"], cwd=clone)
        print(f"pushed main + tags → {MIRROR_REMOTE}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("flow", choices=["netops", "mirror", "collector"])
    parser.add_argument("--push", action="store_true",
                        help="actually push (default: dry-run)")
    args = parser.parse_args()
    if args.flow == "netops":
        return publish_netops(args.push)
    if args.flow == "collector":
        return publish_collector(args.push)
    return publish_mirror(args.push)


if __name__ == "__main__":
    raise SystemExit(main())
