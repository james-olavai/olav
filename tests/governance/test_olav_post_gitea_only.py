"""Governance — olav-post publishes to the internal gitea only, never public.

CLAUDE.md (2026-08-03): olav-post graduated from local-only to its own
standalone repo (ownership_manifest.yaml: owner=olav-post, git=ignore at
root), but the exception is narrow — the internal gitea is the *sole*
allowed remote. Publishing to GitHub/GitLab/PyPI/any CDN stays forbidden.

olav-post/.git is itself gitignored by the root repo (it is a co-located
separate repository, same as olav-doc/olav-web/olav-ent), so this is
dev-machine state, not something a fresh checkout has — the check is
advisory and skips where the nested repo is absent. It denylists known
public git hosts rather than hardcoding the internal gitea address: that
address is a LAN IP and has moved before (project_lan_resubnet_100_to_8),
so pinning it here would make the gate the next thing that breaks on a
resubnet, not the thing that catches a real regression.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_POST = _ROOT / "olav-post"
_PUBLIC_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "pypi.org", "npmjs.com")


def _remotes() -> dict[str, str]:
    if not (_POST / ".git").exists():
        pytest.skip("olav-post is not checked out as its own repo on this machine")
    out = subprocess.run(
        ["git", "-C", str(_POST), "remote", "-v"],
        capture_output=True, text=True, check=True,
    ).stdout
    remotes: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            remotes[parts[0]] = parts[1]
    return remotes


def test_olav_post_has_at_least_one_remote():
    assert _remotes(), "olav-post has no git remote configured"


def test_olav_post_has_no_public_remote():
    remotes = _remotes()
    offenders = {name: url for name, url in remotes.items()
                 if any(host in url for host in _PUBLIC_HOSTS)}
    assert not offenders, (
        f"olav-post has a remote pointing at a public host: {offenders} — "
        "CLAUDE.md forbids publishing olav-post content anywhere but the "
        "internal gitea"
    )
