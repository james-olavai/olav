"""Frozen Python parser registry — ARCH-25.

Loads and saves per-(platform, command) Python parser modules from
``.olav/templates/parsers/<platform>/<command>.py`` (or the `_quarantine/`
sibling for single-sample learns). Mirrors :mod:`etl_registry`.

Rejection logic on :func:`load_parser` is the same three-layer defense:
  * file must exist
  * header stamp must parse and `version == PARSER_CONTRACT_VERSION`
  * recomputed body sha256 must match the stamp

Single-sample learns land in the `_quarantine` tree; callers can use
``prefer_quarantine=True`` to test those explicitly (not auto-loaded into
the fast path unless the caller asks).
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Callable

from olav_netops.core import parser_contract

logger = logging.getLogger(__name__)


def _templates_dir() -> Path:
    """Resolve the frozen-parser base directory from platform paths config.

    Mirrors :mod:`etl_registry._templates_dir` — ETLs live at
    ``.olav/templates/etl/`` and parsers at ``.olav/templates/parsers/``.
    """
    try:
        from olav.core.config import get_paths_config
        base = Path(get_paths_config().agent_dir)
    except Exception:
        base = Path.cwd() / ".olav"
    return base / "templates" / "parsers"


def parsers_dir() -> Path:
    """Primary tree — normal, multi-sample-validated parsers."""
    return _templates_dir()


def quarantine_dir() -> Path:
    """Quarantine tree — single-sample learns held until corroboration."""
    return _templates_dir() / "_quarantine"


def frozen_path(platform: str, command: str, quarantine: bool = False) -> Path:
    """Absolute path to a frozen parser file. Does not create dirs."""
    base = quarantine_dir() if quarantine else parsers_dir()
    safe_cmd = parser_contract.safe_command(command)
    return base / platform / f"{safe_cmd}.py"


def _import_module(path: Path, mod_name: str) -> object | None:
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        logger.warning("parser_registry: import of %s failed: %s", path, exc)
        sys.modules.pop(mod_name, None)
        return None


def _load_at(path: Path, platform: str, command: str, quarantine: bool) -> Callable | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.debug("parser_registry: cannot read %s: %s", path, exc)
        return None

    header = parser_contract.parse_header(text)
    if header is None:
        logger.warning("parser_registry: %s missing/malformed header, ignoring", path)
        return None

    if header.get("version") != parser_contract.PARSER_CONTRACT_VERSION:
        logger.info(
            "parser_registry: %s version=%s != current=%s, ignoring (will re-learn)",
            path, header.get("version"), parser_contract.PARSER_CONTRACT_VERSION,
        )
        return None

    expected_sha = header.get("sha256", "")
    actual_sha = parser_contract.body_sha256(text)
    if expected_sha and actual_sha and expected_sha != actual_sha:
        logger.warning(
            "parser_registry: %s sha256 mismatch (header=%s body=%s), ignoring",
            path, expected_sha, actual_sha,
        )
        return None

    if header.get("platform") != platform:
        logger.warning(
            "parser_registry: %s stamp platform=%s but caller asked %s, ignoring",
            path, header.get("platform"), platform,
        )
        return None
    # Note: command in header is the safe_command form; caller passes the raw.
    if header.get("command") != parser_contract.safe_command(command):
        logger.warning(
            "parser_registry: %s stamp command=%s but caller asked %s, ignoring",
            path, header.get("command"), command,
        )
        return None

    q_tag = "_q" if quarantine else ""
    mod_name = (
        f"olav_netops._frozen_parser._{platform}_"
        f"{parser_contract.safe_command(command)}{q_tag}"
    )
    module = _import_module(path, mod_name)
    if module is None:
        return None

    parse_fn = getattr(module, "parse", None)
    if not callable(parse_fn):
        logger.warning("parser_registry: %s has no top-level ``parse`` callable", path)
        return None
    return parse_fn


def load_parser(
    platform: str,
    command: str,
    prefer_quarantine: bool = False,
) -> Callable | None:
    """Resolve the best frozen parser for (platform, command).

    Lookup order:
      * if ``prefer_quarantine=True``: quarantine first, then main
      * else: main first, then quarantine (single-sample fallback)

    Returns ``None`` if no file passes version + sha256 + platform/command
    stamp matching.
    """
    main_path = frozen_path(platform, command, quarantine=False)
    q_path = frozen_path(platform, command, quarantine=True)

    order: list[tuple[Path, bool]] = (
        [(q_path, True), (main_path, False)]
        if prefer_quarantine
        else [(main_path, False), (q_path, True)]
    )

    for path, is_q in order:
        fn = _load_at(path, platform, command, is_q)
        if fn is not None:
            return fn
    return None


def save_parser(
    platform: str,
    command: str,
    body: str,
    quarantine: bool = False,
) -> Path:
    """Write ``body`` with a stamped header to the frozen parser file.

    ``body`` is the Python source code WITHOUT the header stamp — we add
    it. Returns the path written. Creates parent directories as needed.
    """
    path = frozen_path(platform, command, quarantine=quarantine)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = parser_contract.make_header(platform, parser_contract.safe_command(command), body)
    path.write_text(header + body, encoding="utf-8")
    logger.info(
        "parser_registry: wrote %s (quarantine=%s, %d bytes body)",
        path, quarantine, len(body),
    )
    return path


def invalidate(
    platform: str,
    command: str,
    quarantine: bool = False,
) -> bool:
    """Delete the frozen parser file. Returns True if a file was deleted."""
    path = frozen_path(platform, command, quarantine=quarantine)
    if not path.exists():
        return False
    try:
        path.unlink()
        logger.info("parser_registry: removed %s", path)
        return True
    except Exception as exc:
        logger.warning("parser_registry: could not remove %s: %s", path, exc)
        return False
