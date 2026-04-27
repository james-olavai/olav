"""
.olav/workspace/config/discovery/tools/scaffold_domain_agent.py
────────────────────────────────────────────────────────────────
Discovery tool: scaffold a new domain agent or skill workspace directory.

Given a domain name, kind (Agent | Skill), description, and routing keywords,
this tool generates the minimum set of files needed to register the domain with
the OLAV platform:

  <workspace_root>/<name>/
  ├── MANIFEST.yaml           # route registration & metadata
  ├── AGENT.md  (Agent kind)  # LLM-readable agent descriptor
  ├── SKILL.md  (Skill kind)  # LLM-readable skill descriptor
  └── tools/    (optional)    # placeholder for tool scripts

Design reference: dev_docs/olav_platform.md §7.2 + §7.6 (渐进式披露约束)

Security: this tool NEVER writes to shared DuckDB / shared storage.
All mutations must go through SchemaMutationService (§7.7 writing boundary).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_VALID_KINDS = {"Agent", "Skill"}
_DEFAULT_VERSION = "0.11.0"


def scaffold_domain_agent(
    name: str,
    kind: str,
    description: str,
    route_keywords: list[str],
    workspace_root: Path | str = Path(".olav/workspace"),
    *,
    agent: str | None = None,
    version: str = _DEFAULT_VERSION,
    tools_dir: str | None = None,
    requires: list[str] | None = None,
    create_tools_dir: bool = False,
    create_references_dir: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate workspace files for a new domain agent or skill.

    Parameters
    ----------
    name:
        Domain/skill identifier, e.g. ``"itsm"``.  Used as the subdirectory
        name under *workspace_root*.
    kind:
        ``"Agent"`` or ``"Skill"``.
    description:
        Human-readable description written into AGENT.md / SKILL.md.
    route_keywords:
        Natural-language utterances added to ``MANIFEST.yaml``
        ``route_keywords`` for the semantic router.
    workspace_root:
        Root directory under which ``<name>/`` will be created.
        Defaults to ``.olav/workspace``.
    agent:
        For Skill kind only — the parent agent this skill registers to
        (written to ``MANIFEST.yaml`` ``agent:`` field).
    version:
        Semantic version string for ``MANIFEST.yaml``.
    tools_dir:
        Relative path to write into MANIFEST ``tools_dir`` field.
        Defaults to ``"tools/"`` when *create_tools_dir* is ``True``.
    requires:
        Python package requirements list for ``MANIFEST.yaml``.
    create_tools_dir:
        If ``True``, also create an empty ``tools/`` subdirectory.
    create_references_dir:
        If ``True`` (default), create a ``references/`` subdirectory with a
        placeholder README.  This is the *Reference* layer of the three-tier
        progressive disclosure constraint (§7.6). Set ``False`` only when no
        external specs or payloads are expected.
    overwrite:
        If ``False`` (default), skip files that already exist (idempotent).
        If ``True``, overwrite existing files.

    Returns
    -------
    dict with keys:
        - ``name``: the domain name
        - ``workspace_dir``: absolute path to the created directory (str)
        - ``created_files``: list of str paths actually written
        - ``skipped_files``: list of str paths skipped (already existed)

    Raises
    ------
    ValueError
        If *kind* is not ``"Agent"`` or ``"Skill"``.
    """
    if kind not in _VALID_KINDS:
        raise ValueError(
            f"Invalid kind={kind!r}. Must be one of {sorted(_VALID_KINDS)}"
        )

    workspace_root = Path(workspace_root)
    domain_dir = workspace_root / name
    domain_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    skipped: list[str] = []

    # ── MANIFEST.yaml ─────────────────────────────────────────────────────────
    effective_tools_dir = tools_dir or ("tools/" if create_tools_dir else None)
    manifest_data: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "version": version,
        "route_keywords": list(route_keywords),
    }
    if agent is not None:
        manifest_data["agent"] = agent
    if effective_tools_dir is not None:
        manifest_data["tools_dir"] = effective_tools_dir
    if requires:
        manifest_data["requires"] = list(requires)

    manifest_path = domain_dir / "MANIFEST.yaml"
    _write_file(
        manifest_path,
        yaml.dump(manifest_data, default_flow_style=False, sort_keys=False),
        overwrite=overwrite,
        created=created,
        skipped=skipped,
    )

    # ── AGENT.md / SKILL.md ───────────────────────────────────────────────────
    if kind == "Agent":
        agent_md_content = _render_agent_md(name, description)
        _write_file(
            domain_dir / "AGENT.md",
            agent_md_content,
            overwrite=overwrite,
            created=created,
            skipped=skipped,
        )
    else:  # Skill
        skill_md_content = _render_skill_md(name, description)
        _write_file(
            domain_dir / "SKILL.md",
            skill_md_content,
            overwrite=overwrite,
            created=created,
            skipped=skipped,
        )

    # ── tools/ directory ──────────────────────────────────────────────────────
    if create_tools_dir:
        tools_path = domain_dir / "tools"
        tools_path.mkdir(exist_ok=True)
        # write a .gitkeep so the empty directory is tracked
        gitkeep = tools_path / ".gitkeep"
        _write_file(
            gitkeep,
            "",
            overwrite=overwrite,
            created=created,
            skipped=skipped,
        )

    # ── references/ directory (Reference layer — 渐进式披露 §7.6) ────────────
    if create_references_dir:
        refs_path = domain_dir / "references"
        refs_path.mkdir(exist_ok=True)
        readme_content = _render_references_readme(name)
        _write_file(
            refs_path / "README.md",
            readme_content,
            overwrite=overwrite,
            created=created,
            skipped=skipped,
        )

    return {
        "name": name,
        "workspace_dir": str(domain_dir),
        "created_files": created,
        "skipped_files": skipped,
    }


# ── helpers ───────────────────────────────────────────────────────────────────


def _write_file(
    path: Path,
    content: str,
    *,
    overwrite: bool,
    created: list[str],
    skipped: list[str],
) -> None:
    if path.exists() and not overwrite:
        skipped.append(str(path))
        return
    path.write_text(content, encoding="utf-8")
    created.append(str(path))


def _render_agent_md(name: str, description: str) -> str:
    return f"""\
---
name: {name}
type: agent
static_context:
  - path: ./references/README.md
---

# {name.capitalize()} Agent

{description}

## Capabilities

- (Add capabilities here)

## Tools

- (Add tool references here)

## Notes

This file was auto-generated by `scaffold_domain_agent`.
Edit to add domain-specific context before deployment.
"""


def _render_skill_md(name: str, description: str) -> str:
    return f"""\
---
name: {name}
type: skill
static_context:
  - path: ./references/README.md
---

# {name.capitalize()} Skill

{description}

## Usage

- (Describe how to invoke this skill)

## Notes

This file was auto-generated by `scaffold_domain_agent`.
Edit to add domain-specific context before deployment.
"""


def _render_references_readme(name: str) -> str:
    return f"""\
# {name.capitalize()} — Reference Materials

This directory holds the **Reference layer** for the `{name}` domain
(olav_platform.md §7.6 渐进式披露 three-tier constraint).

Files placed here are loaded on-demand via the `static_context` mechanism
in AGENT.md / SKILL.md — they are NOT included in the base system prompt.

## What belongs here

- OpenAPI / AsyncAPI specification files (`openapi.yaml`)
- Example payloads (`examples/*.json`)
- Authentication flow descriptions (`auth.md`)
- Vendor-specific CLI reference tables (`cli_reference.md`)
- Any large reference document that should only be injected when needed

## What does NOT belong here

- Execution logic (goes in `tools/`)
- Agent routing metadata (goes in `MANIFEST.yaml`)
- Capability descriptions (goes in AGENT.md / SKILL.md)

## Usage

Add entries to the `static_context:` list in AGENT.md or SKILL.md:

```yaml
static_context:
  - path: ./references/openapi.yaml
  - path: ./references/auth.md
```
"""
