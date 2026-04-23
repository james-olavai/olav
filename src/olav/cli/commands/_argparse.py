"""Shared argparse helper for CLI subcommand argument parsing.

Why this module exists
----------------------
OLAV's CLI subcommands (``olav skill``, ``olav agent``, ``olav admin``,
``olav workspace``, ``olav service``, ``olav registry``, ``olav kb``,
``olav sessions``, ``olav export``, ``olav log``) each receive their
"rest of argv" via argparse's ``nargs=argparse.REMAINDER``.  The
receiving function then almost always does:

.. code-block:: python

   import shlex
   parts = shlex.split(args.strip()) if args.strip() else []

That snippet appears in ~10 files.  Duplication aside, the handlers
treat edge cases inconsistently:

* some forget the ``if args.strip()`` guard and crash on ``None``
* some accept already-split lists (``nargs="*"``) while others expect
  a single string — calling conventions are unclear
* quoting failure modes differ (some use ``posix=True`` implicitly,
  some don't), which leads to Windows path handling bugs
* error behaviour on unmatched quotes varies

This helper consolidates all of that into a single well-tested entry
point.  First adopter is :mod:`olav.cli.commands.agent_install`;
Phase 7 sweeps the remaining call sites.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable


def parse_subcommand_args(raw: str | Iterable[str] | None) -> list[str]:
    """Return a list of non-empty string tokens for a subcommand.

    Accepts either the raw string captured by ``argparse.REMAINDER``
    (including ``None`` when no extra args were given) or a
    pre-split iterable of strings (when a parent parser uses
    ``nargs="*"``).  Always returns a plain list so callers can
    slice / index / unpack uniformly.

    Behaviour:

    * ``None`` → ``[]``
    * empty / whitespace-only string → ``[]``
    * string → :func:`shlex.split` (POSIX), which honours single /
      double quotes and backslash escapes.  Unmatched quotes bubble
      :class:`ValueError` up so the caller can render a clean error.
    * iterable → coerced to list, with empty / whitespace-only
      elements filtered (guards against ``["install", "", "  "]``
      from lazy parent parsers).

    Args:
        raw: Input as captured by argparse.  ``None`` is safe.

    Returns:
        A list of non-empty argument tokens.

    Raises:
        ValueError: When *raw* is a string with unmatched quotes.
            :class:`shlex.split` raises a lower-level
            ``ValueError("No closing quotation")`` / similar; we let
            it propagate so callers can show a usage hint.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        return shlex.split(stripped)
    # Assume iterable of strings — filter out empty/whitespace-only.
    return [token for token in raw if isinstance(token, str) and token.strip()]


__all__ = ["parse_subcommand_args"]
