"""Python parser contract — ARCH-25.

Defines the callable signature, validation, and header-stamp format for every
frozen Python parser produced by :mod:`olav_netops.core.parser_learner`.

A frozen parser is a plain Python module at
``.olav/templates/parsers/<platform>/<command>.py`` (or under the
``_quarantine/`` subtree for single-sample learns) containing one top-level
``parse(raw: str, sample_hint: dict | None = None) -> list[dict]`` function
plus a header stamp comment carrying the contract version + sha256 of the
body. The registry rejects files whose version or hash don't match.

Header stamp is **decoupled from the ETL contract** (`etl_contract.py`) —
bumping `PARSER_CONTRACT_VERSION` invalidates only parsers, not ETLs.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)


PARSER_CONTRACT_VERSION = "2"  # ARCH-26: netutils-aware prompt


class PythonParserFn(Protocol):
    """Signature every frozen parser MUST implement.

    ``raw`` — the device's verbatim CLI output (one device at a time).

    ``sample_hint`` — optional dict that the caller may pass to signal
    things like expected record count, vendor quirks, or the originating
    device's platform. Parsers MUST accept but MAY ignore it (defaults
    to None so callers can omit).

    Returns a flat ``list[dict]`` — one dict per logical record. Keys
    SHOULD be lowercase snake_case; the caller (ETL layer) normalizes
    any per-protocol schema mapping downstream.
    """

    def __call__(
        self,
        raw: str,
        sample_hint: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


def validate_parser_output(
    rows: list[dict[str, Any]],
    min_records: int = 0,
    max_records: int = 10000,
) -> tuple[bool, str]:
    """Shallow shape validation for a parser's output.

    Returns ``(ok, err)`` — ``err`` empty on success.

    ``min_records=0`` (the default) accepts empty lists — some legitimate
    outputs have nothing to parse (e.g. "BGP not active" on a device where
    the protocol isn't configured). Callers that need a positive floor
    should pass a ``min_records > 0`` based on upstream signals.
    """
    if not isinstance(rows, list):
        return False, f"parser returned {type(rows).__name__}, expected list"

    n = len(rows)
    if n < min_records:
        return False, f"too few records ({n} < {min_records})"
    if n > max_records:
        return False, f"too many records ({n} > {max_records})"

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            return False, f"row {i} is not a dict (got {type(row).__name__})"

    return True, ""


def make_header(platform: str, command: str, body: str) -> str:
    """Format the header stamp written to every frozen parser.

    Header is deliberately distinct from ETL's so that version checks
    on each layer are independent.
    """
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        f"# olav-pac-parser v{PARSER_CONTRACT_VERSION} "
        f"platform={platform} command={command} "
        f"generated={now} sha256={digest}\n"
    )


def parse_header(text: str) -> dict[str, str] | None:
    """Parse the first non-empty line as a frozen-parser header stamp.

    Returns a dict with ``version, platform, command, generated, sha256``
    keys or ``None`` if the line is missing or malformed.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("# olav-pac-parser"):
            return None
        tokens = stripped.split()
        # "# olav-pac-parser vN platform=... command=... generated=... sha256=..."
        if len(tokens) < 7:
            return None
        out: dict[str, str] = {}
        if not tokens[2].startswith("v"):
            return None
        out["version"] = tokens[2][1:]
        for tok in tokens[3:]:
            if "=" not in tok:
                continue
            k, _, v = tok.partition("=")
            out[k] = v
        if {"platform", "command", "sha256"}.issubset(out.keys()):
            return out
        return None
    return None


def body_sha256(text: str) -> str:
    """Return the sha256 (first 16 hex chars) of the body — every line
    AFTER the first ``# olav-pac-parser`` header line."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip().startswith("# olav-pac-parser"):
            body = "".join(lines[i + 1:])
            return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return ""


def safe_command(command: str) -> str:
    """Normalize a command string for filesystem use — matches
    :func:`olav_netops.core.auto_learn._template_path` conventions so
    the parser filename lines up with the textfsm filename."""
    return command.strip().lower().replace(" ", "_").replace("/", "_")[:60]
