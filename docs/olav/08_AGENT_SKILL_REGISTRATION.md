# Agent And Skill Registration

This document explains how agent and skill registration works in the current OLAV platform.

The key point is that OLAV currently has two registration paths:

1. Static in-tree declaration through `AGENT.md`.
2. Manifest-driven injection for package-managed extensions.

`SKILL.md` is important, but it is not the only registration mechanism.

## 1. Current Registration Model

### Path A: Static built-in registration

Built-in platform skills are commonly declared directly in an agent's `AGENT.md` frontmatter through `subagents` entries.

Example pattern:

```yaml
subagents:
  - path: ./discovery/SKILL.md
  - path: ./creator/SKILL.md
  - path: ./knowledge/SKILL.md
```

This is the current baseline pattern for in-repo platform skills.

Concrete example shape:

```text
.olav/workspace/config/
├── AGENT.md
├── MANIFEST.yaml
├── creator/
│   └── SKILL.md
├── discovery/
│   └── SKILL.md
└── tools/
```

### Path B: Manifest-driven extension injection

For package-managed or externally installed capabilities, OLAV scans `.olav/workspace/` recursively for `MANIFEST.yaml` files.

During agent assembly, the platform:

1. Discovers manifests.
2. Filters them by `kind: Skill`.
3. Keeps only manifests whose `agent` field matches the current agent.
4. Verifies that a sibling `SKILL.md` exists.
5. Injects the skill path into the target agent config only if it was not already declared explicitly.

Explicit `AGENT.md` declarations always win.

## 2. Agent Registration

An agent workspace entry is expected to have its own directory under `.olav/workspace/<agent>/`.

Typical agent-level files are:

- `AGENT.md`
- `MANIFEST.yaml`
- `prompts/`
- `tools/`

The current manifest discovery model expects `MANIFEST.yaml` to carry at least:

- `name`
- `kind`

Commonly used fields in the current implementation also include:

- `version`
- `route_keywords`
- `tools_dir`
- `requires`
- `provider_package`
- `required_modules`
- `required_binaries`
- `config_namespace`

## 3. Skill Registration

For a manifest-driven skill, the important fields are:

- `name`
- `kind: Skill`
- `version`
- `agent`  — the parent agent this skill registers to

The current injection logic also requires a sibling `SKILL.md` next to that manifest.

Minimal shape:

```yaml
kind: Skill
name: sync
version: "0.11.0"
agent: config
requires:
  - olav-netops>=0.11
provider_package: olav-netops
```

Concrete example shape:

```text
source-extension/
├── MANIFEST.yaml
├── SKILL.md
└── tools/
  ├── execute_sync.py
  └── helpers.py
```

Typical install flow:

```bash
uv run olav workspace install ./source-extension
uv run olav workspace validate sync
uv run olav workspace status
```

## 4. What `SKILL.md` Actually Does

`SKILL.md` has two important roles today:

1. It documents the skill's purpose, prompt contract, and available tools.
2. It is used to validate the declared tool list against discovered tools.

But `SKILL.md` alone is not the runtime loading mechanism.

Tool loading is performed from Python modules in `tools/`, while `SKILL.md` acts as documentation and validation metadata.

This is an important distinction:

- `SKILL.md` is necessary for skill packaging and prompt assembly.
- `tools/*.py` provide actual tool implementations.
- `MANIFEST.yaml` enables package-managed discovery/injection.

## 5. Workspace Lifecycle Commands

The current workspace control plane exposes these platform commands:

- `olav workspace install <source>`
- `olav workspace validate <name>`
- `olav workspace status`
- `olav workspace diff`
- `olav workspace upgrade <name>`
- `olav workspace disable <name>`
- `olav workspace remove <name>`
- `olav workspace rollback <name> --from <archive_dir>`

Practical meaning:

1. `install` copies a source directory with `MANIFEST.yaml` into `.olav/workspace/<manifest.name>`.
2. `validate` parses the manifest and checks dependency availability.
3. `status` shows whether entries are managed, enabled, and dependency-complete.

## 6. The `olav skills` CLI Is Not Full Registration

The `olav skills create <name> --agent <agent>` helper currently creates a `SKILL.md` template under an existing agent's `tools/` subtree.

That is useful for authoring, but it is not the full package-managed registration path.

In other words:

1. `olav skills create` helps scaffold documentation.
2. It does not create `MANIFEST.yaml`.
3. It does not by itself turn a capability into a package-managed workspace entry.

## 7. Recommended Authoring Model

Use these rules when adding capabilities:

### For built-in platform skills

1. Add the skill under the target agent directory.
2. Add its `SKILL.md`.
3. Add its Python tools under `tools/`.
4. Declare it explicitly in that agent's `AGENT.md` if it is a built-in capability.

### For package-managed extension skills

1. Create a dedicated workspace entry with `MANIFEST.yaml`.
2. Set `kind: Skill` and `agent: <target-agent>`.
3. Add a sibling `SKILL.md`.
4. Provide runtime implementation and dependency metadata.
5. Install it through the workspace control plane.

## 8. Minimal Authoring Walkthrough

For a new managed skill, the smallest practical flow is:

1. Create a source directory.
2. Write `MANIFEST.yaml` with `kind: Skill`, `name`, and `agent`.
3. Add a sibling `SKILL.md`.
4. Add tool implementations under `tools/`.
5. Install with `olav workspace install <source_dir>`.
6. Validate with `olav workspace validate <name>`.
7. Check visibility with `olav workspace status`.

For a built-in skill, the smallest practical flow is:

1. Add the skill directory under an existing agent directory.
2. Add `SKILL.md`.
3. Add runtime tools.
4. Reference it explicitly from the parent `AGENT.md`.

## 9. What This Document Does Not Claim

This document does not claim that OLAV currently has:

1. A single universal registration path for every built-in and external skill.
2. A fully dynamic plugin model that hot-loads arbitrary dependencies without package installation.
3. A UI-based registration flow.

The current platform is intentionally hybrid: static declarations for built-ins, manifest-driven injection for managed extensions.

## 10. Related Docs

- [03_CORE_CONCEPTS.md](./03_CORE_CONCEPTS.md)
- [06_AAA.md](./06_AAA.md)
- [07_API_OPENAPI.md](./07_API_OPENAPI.md)
- [09_EXTENSION_LIFECYCLE.md](./09_EXTENSION_LIFECYCLE.md)