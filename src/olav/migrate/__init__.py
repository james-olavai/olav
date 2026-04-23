"""OLAV migration scripts.

This package owns one-shot data / layout migrations that run on user
machines as part of a version upgrade.  Each migration ships as a
module named after the target version it prepares the system for:

* :mod:`olav.migrate.v0_20_layout` — Phase B (v0.20.2) filesystem
  alignment: ``.olav/workspace/<name>/AGENT.md`` →
  ``.deepagents/agents/<name>/AGENTS.md`` + subagent directory
  flattening.

Design principles followed by every migration module here:

1. **Dry-run first** — a pure ``plan_*`` function that reads state
   and returns a declarative operation list.  Zero side effects.
2. **Idempotent** — ``apply_*`` on an already-migrated tree is a
   no-op (detected via ``already_migrated``).
3. **Backup by default** — ``apply_*`` tars the old layout into
   ``.olav.bak/`` before making changes; ``--no-backup`` opts out.
4. **Human-readable** — the plan object exposes ``summary()`` for
   CLI output and ``as_dict()`` for JSON / machine consumption.
"""
