"""skill install installed-package resolution (dev_docs/99 §7.6 follow-up, 0.22.0).

``olav skill install olav-netops`` must work for pip users with no source
tree: resolution order is git/archive URL → existing local path →
installed package's bundled ``<pkg>/data/skillpack/``.

Covers:
1. resolver finds the real olav_netops bundle (installed in this venv)
2. distribution-name normalization (olav-netops ≡ olav_netops)
3. unknown package / package without skillpack / path-like input → None
4. _install falls back to the resolver and the error message carries the
   pip hint when nothing resolves
5. existing local path still wins over an installed package (CI contract)
6. end-to-end (patched heavies): package-resolved install deploys the
   netops workspace into a fresh cwd
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from olav.cli.commands.skill import SkillCommand, _resolve_installed_skillpack


# ---------------------------------------------------------------------------
# resolver
# ---------------------------------------------------------------------------


def test_resolver_finds_real_netops_bundle() -> None:
    path = _resolve_installed_skillpack("olav_netops")
    assert path is not None, "installed olav_netops must expose data/skillpack"
    assert (path / "workspace.yaml").is_file()
    assert (path / ".olav" / "workspace" / "netops" / "SKILL.md").is_file()


def test_resolver_normalizes_hyphenated_name() -> None:
    assert _resolve_installed_skillpack("olav-netops") == _resolve_installed_skillpack(
        "olav_netops"
    )


def test_resolver_unknown_package_returns_none() -> None:
    assert _resolve_installed_skillpack("definitely-not-a-real-package-xyz") is None


def test_resolver_package_without_skillpack_returns_none() -> None:
    # yaml is installed but ships no data/skillpack
    assert _resolve_installed_skillpack("yaml") is None


def test_resolver_pathlike_input_returns_none() -> None:
    assert _resolve_installed_skillpack("foo/bar") is None
    assert _resolve_installed_skillpack("../etc") is None


# ---------------------------------------------------------------------------
# _install dispatch
# ---------------------------------------------------------------------------


def _install(args: list[str]) -> str:
    return asyncio.run(SkillCommand()._install(args))


def test_install_unknown_name_error_carries_pip_hint(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = _install(["no-such-skillpack"])
    assert "error" in result
    assert "pip install no-such-skillpack" in result


def test_install_existing_file_still_reports_not_a_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "afile").write_text("x", encoding="utf-8")
    result = _install(["afile"])
    assert "not a directory" in result


def test_install_local_path_wins_over_installed_package(tmp_path, monkeypatch) -> None:
    """CI contract: in the monorepo checkout, `olav skill install olav-netops`
    must keep resolving to the ./olav-netops directory, not the pip bundle."""
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "olav-netops"
    local.mkdir()  # exists but has no workspace.yaml/MANIFEST.yaml

    result = _install(["olav-netops"])

    # The local dir was used (and correctly rejected for missing manifests) —
    # NOT the installed package bundle, which would have succeeded.
    assert "neither workspace.yaml nor MANIFEST.yaml" in result


def test_package_resolved_install_deploys_netops_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    # Patch the heavy post-install extras (embedding-backed guide priming);
    # copy/registry logic is what this test asserts.
    import olav.core.memory.guide_kb as guide_kb

    monkeypatch.setattr(guide_kb, "prime_workspace_guides", lambda *a, **kw: "skipped (test)")

    result = _install(["olav-netops"])

    assert "error" not in result.split("\n")[0], f"install failed: {result}"
    assert (tmp_path / ".olav" / "workspace" / "netops" / "SKILL.md").is_file(), (
        f"netops workspace not deployed: {result}"
    )
    # audit deploys too on a fresh tree (platform-owned guard only skips
    # when it already exists)
    assert (tmp_path / ".olav" / "workspace" / "audit" / "SKILL.md").is_file()
