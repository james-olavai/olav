"""agent_install.py — Scaffold for the ``olav agent install`` verb.

Introduced in v0.20.0 as part of Phase 5 of the deepagents migration
(see `dev_docs/53. DEEPAGENTS_MIGRATION_EVALUATION.md` §16 and
`dev_docs/54. PHASE_5_GRAPH_FACTORY.md` §7).

Until v0.20.2 (Phase 1), this command is a thin shim that forwards
every invocation to :class:`olav.cli.commands.skill.SkillCommand`.
That keeps user-visible behaviour identical while we introduce the
new verb name — same code path, same outputs, same failure modes —
so users can start migrating their scripts today:

.. code-block:: shell

    # v0.20.0 — both forms work
    olav skill install /path/to/olav-netops/
    olav agent install /path/to/olav-netops/

In v0.20.2 the implementation moves into this module and ``skill``
becomes the deprecation shim instead.  In v0.20.3 the ``skill``
subcommand is removed entirely.  See §13 of the evaluation doc.

Why a separate verb at all
--------------------------
``deepagents-code`` has its own ``deepagents skills`` subcommand that
creates / lists / deletes *individual* ``SKILL.md`` files.  OLAV's
install handles a much bigger unit — a whole agent package with
``pyproject.toml``, entry points, multiple sub-agents, and workspace
layout.  Calling both "skill" invites user confusion once we're
sharing a terminal with deepagents's verbs, hence the rename to
``agent``.
"""

from __future__ import annotations

import logging

from olav.cli.commands.base import BaseCommand

logger = logging.getLogger(__name__)


class AgentInstallCommand(BaseCommand):
    """User-facing ``olav agent ...`` subcommands.

    Phase 5 (v0.20.0) only wires the ``install`` sub-verb; ``list`` /
    ``remove`` / ``update`` come with later phases.  Unknown
    sub-verbs return a helpful usage string instead of raising.
    """

    def __init__(self) -> None:
        super().__init__(
            name="agent",
            description="Install and manage OLAV agent packages",
        )

    async def execute(self, args: str = "") -> str:
        """Dispatch the sub-verb.

        Args:
            args: Raw argument string captured by argparse's
                ``REMAINDER`` (e.g. ``"install /path/to/pkg"``).

        Returns:
            Human-readable result line(s) — typed as a string so the
            caller can pass the whole thing to ``console.print``.
        """
        from olav.cli.commands._argparse import parse_subcommand_args

        parts = parse_subcommand_args(args)
        if not parts:
            return self._usage()
        sub = parts[0]
        if sub == "install":
            return await self._install(parts[1:])
        return f"unknown agent action: {sub}\n{self._usage()}"

    async def _install(self, parts: list[str]) -> str:
        """Forward to :class:`SkillCommand` — same code path, new name.

        We import SkillCommand lazily so this module is cheap to
        import even when the heavy workspace-installer dependencies
        (git, tarfile, hashlib, langchain) aren't needed.

        Args:
            parts: The positional arguments after ``install``, already
                shell-split.  Passed through verbatim — nothing is
                renamed, dropped, or re-parsed; SkillCommand's own
                flag handling applies (``--merge-into``, `--copy` once
                P1 lands, etc.).

        Returns:
            Whatever SkillCommand returns.
        """
        if not parts:
            return (
                "usage: olav agent install <path|git_url|archive_url> "
                "[--merge-into <workspace>]"
            )
        # Quote each piece so shlex.split inside SkillCommand reassembles
        # them correctly even when a path contains spaces.
        import shlex

        forwarded = "install " + " ".join(shlex.quote(p) for p in parts)

        from olav.cli.commands.skill import SkillCommand

        return await SkillCommand().execute(forwarded)

    @staticmethod
    def _usage() -> str:
        return (
            "usage: olav agent <action> [args]\n"
            "  install <path|git_url|archive_url>   Install an agent package\n"
            "    --merge-into <workspace>           Merge SkillPack into an existing workspace"
        )


__all__ = ["AgentInstallCommand"]
