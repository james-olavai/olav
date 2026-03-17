# Extension Lifecycle

This document explains how a package-managed extension moves through its lifecycle in the current OLAV platform.

It applies to agent entries and skill entries managed through `.olav/workspace/` and the `olav workspace ...` control-plane commands.

## 1. Lifecycle Stages

The current lifecycle is:

1. Author
2. Install
3. Validate
4. Use
5. Upgrade
6. Disable
7. Remove
8. Rollback

This is a control-plane lifecycle. It is separate from the agent's own runtime tool execution.

## 2. Author

Authoring happens in a source directory before installation into `.olav/workspace/`.

For a managed extension entry, the source directory should contain at least:

- `MANIFEST.yaml`
- `SKILL.md` or `AGENT.md`
- runtime implementation files such as `tools/*.py`

For manifest-driven skills, the manifest must identify the target parent agent through the `agent` field.

## 3. Install

Current install command:

```bash
uv run olav workspace install <source_dir>
```

What install does today:

1. Verifies that the source directory exists.
2. Verifies that `MANIFEST.yaml` exists.
3. Parses the manifest.
4. Copies the directory into `.olav/workspace/<manifest.name>`.
5. Reports dependency warnings if the manifest declares missing runtime dependencies.

Install is a control-plane action and should be treated as admin-only.

## 4. Validate

Current validate command:

```bash
uv run olav workspace validate <name>
```

What validate does today:

1. Confirms the workspace entry exists.
2. Confirms `MANIFEST.yaml` exists.
3. Parses the manifest.
4. Checks dependency availability.
5. Returns either success or a dependency-unavailable result.

Validation is the platform's current gate between “declared” and “usable”.

## 5. Discover And Inject

Once installed, the agent builder can discover the extension.

The current discovery path is:

1. Recursively scan `.olav/workspace/` for `MANIFEST.yaml`.
2. Parse those manifests into `AgentManifest` objects.
3. During agent assembly, merge matching skill manifests into the target agent config.
4. Never remove explicit `AGENT.md` declarations.

This means installation alone does not immediately guarantee visibility everywhere. The entry still has to pass the runtime discovery and merge rules.

## 6. Status And Diff

Useful inspection commands:

```bash
uv run olav workspace status
uv run olav workspace diff
```

Current meanings:

- `status` shows whether entries are managed or user-owned, enabled or disabled, and whether dependencies are satisfied.
- `diff` compares local version markers against upstream version markers.

These are observability commands for the control plane.

## 7. Upgrade

Current upgrade command:

```bash
uv run olav workspace upgrade <name>
```

Current behavior:

1. Refuses to upgrade unmanaged entries.
2. Prefers `.upstream-version` when present.
3. Otherwise attempts to resolve upstream version from installed package metadata.
4. Updates the local `.version` marker.

The current implementation is version-marker oriented. It is not yet a full remote package fetch-and-reinstall workflow.

## 8. Disable

Current disable command:

```bash
uv run olav workspace disable <name>
```

Current behavior:

1. Confirms the workspace entry exists.
2. Writes a `.disabled` marker.

Disable is a control-plane state change. It does not rewrite the source package; it marks the installed workspace entry as disabled.

## 9. Remove

Current remove command:

```bash
uv run olav workspace remove <name>
```

Current behavior:

1. Refuses to remove unmanaged entries.
2. Deletes the installed workspace directory.

This is a destructive control-plane action and should be treated as admin-only.

## 10. Rollback

Current rollback command:

```bash
uv run olav workspace rollback <name> --from <archive_dir>
```

Current behavior:

1. Verifies the archived entry exists.
2. Replaces the current workspace entry with the archived one.

Rollback assumes you already have an archive source. The current platform does not yet provide a full built-in versioned artifact store.

## 11. Practical Operating Rules

Use these rules in day-to-day operations:

1. Treat install, upgrade, disable, remove, and rollback as admin control-plane actions.
2. Run `validate` after installation and before first use.
3. Use `status` to separate dependency problems from prompt/tool problems.
4. Remember that built-in skills and manifest-driven skills are not identical lifecycle paths.

## 12. What This Document Does Not Claim

This document does not claim that OLAV already has:

1. A full package registry UI.
2. Automatic rollback snapshots.
3. A universal hot-plug model for arbitrary runtime dependencies.

The current model is intentionally conservative: package-managed entries move through a visible control-plane lifecycle, with validation and dependency checks at each stage.

## 13. Related Docs

- [06_AAA.md](./06_AAA.md)
- [07_API_OPENAPI.md](./07_API_OPENAPI.md)
- [08_AGENT_SKILL_REGISTRATION.md](./08_AGENT_SKILL_REGISTRATION.md)