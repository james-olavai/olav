"""Guard: olav and olav-netops must carry the same version string, and the
olav-netops dependency pin on olav must not fall behind the current version.

Why this matters: both packages are released together as a unit. Version
skew has historically caused ``pip install olav-netops`` to pull an older
olav wheel from PyPI, masking new APIs or breaking the netops plugin load.

Four invariants enforced:
  1. olav version == olav-netops version (lock-step releases)
  2. olav-netops pyproject.toml ``olav>=X`` pin is not older than current olav
  3. src/olav/__init__.__version__ matches pyproject.toml (no manual drift)
  4. netops skillpack workspace.yaml versions match (both the repo-root copy
     and the wheel-shipped data/skillpack copy — `olav skill install` prints
     the yaml's version, which shipped as a stale "v0.22.2" while the
     package itself was 0.23.1)
"""

from __future__ import annotations

import re
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parents[2]

_OLAV_PYPROJECT = REPO / "pyproject.toml"
_NETOPS_PYPROJECT = REPO / "olav-netops" / "pyproject.toml"
_INIT_PY = REPO / "src" / "olav" / "__init__.py"


def _read_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _parse_version(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in s.strip().split("."))


def test_olav_and_netops_versions_match():
    """olav and olav-netops must carry identical version strings."""
    olav_ver = _read_toml(_OLAV_PYPROJECT)["project"]["version"]
    netops_ver = _read_toml(_NETOPS_PYPROJECT)["project"]["version"]
    assert olav_ver == netops_ver, (
        f"Version skew: olav={olav_ver!r}, olav-netops={netops_ver!r}. "
        "Both packages are released as a unit — bump them together."
    )


def test_netops_dependency_pin_not_stale():
    """olav-netops must require olav >= its own version (no stale lower bound)."""
    olav_ver = _read_toml(_OLAV_PYPROJECT)["project"]["version"]
    netops_deps: list[str] = _read_toml(_NETOPS_PYPROJECT)["project"]["dependencies"]

    olav_dep = next((d for d in netops_deps if d.startswith("olav")), None)
    assert olav_dep is not None, (
        "olav-netops/pyproject.toml has no 'olav' dependency entry."
    )

    m = re.search(r">=\s*([\d.]+)", olav_dep)
    assert m, (
        f"Could not parse olav>= pin from dependency string: {olav_dep!r}. "
        "Expected format: 'olav>=X.Y.Z'."
    )

    pin_ver = m.group(1)
    assert _parse_version(pin_ver) >= _parse_version(olav_ver), (
        f"olav-netops pins olav>={pin_ver} but current olav is {olav_ver}. "
        "Update the dependency pin in olav-netops/pyproject.toml."
    )


_WORKSPACE_YAMLS = (
    REPO / "olav-netops" / "workspace.yaml",
    REPO / "olav-netops" / "src" / "olav_netops" / "data" / "skillpack" / "workspace.yaml",
)


def test_netops_skillpack_workspace_yaml_versions_match():
    """Both netops workspace.yaml copies must carry the package version.

    `olav skill install olav-netops` reports the version from the wheel's
    data/skillpack/workspace.yaml — a stale value there tells users they
    installed an older release than they actually did.
    """
    netops_ver = _read_toml(_NETOPS_PYPROJECT)["project"]["version"]
    for yaml_path in _WORKSPACE_YAMLS:
        text = yaml_path.read_text(encoding="utf-8")
        m = re.search(r'^version:\s*["\']?([\d.]+)["\']?', text, re.MULTILINE)
        assert m, f"Could not find version: line in {yaml_path}"
        assert m.group(1) == netops_ver, (
            f"{yaml_path.relative_to(REPO)} declares version {m.group(1)!r} but "
            f"olav-netops is {netops_ver!r}. Bump the workspace.yaml versions "
            "together with the package (they are what `olav skill install` prints)."
        )


def test_init_py_version_matches_pyproject():
    """src/olav/__init__.__version__ must match pyproject.toml."""
    pyproject_ver = _read_toml(_OLAV_PYPROJECT)["project"]["version"]

    init_text = _INIT_PY.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.MULTILINE)
    assert m, f"Could not find __version__ assignment in {_INIT_PY}"

    init_ver = m.group(1)
    assert init_ver == pyproject_ver, (
        f"__version__ in src/olav/__init__.py ({init_ver!r}) does not match "
        f"pyproject.toml ({pyproject_ver!r}). Update __init__.py."
    )
