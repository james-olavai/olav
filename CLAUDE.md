# CLAUDE.md — OLAV Platform Repository Instructions

## Repository Structure

This is the `olav` root repository — the **platform base** (control plane, runtime, CLI, plugin contracts, shared infrastructure). Five delivery units coexist:

| Unit | Location | Role |
|---|---|---|
| `olav` | `src/olav/`, root configs | Platform core — CLI, runtime, workspace lifecycle, audit, auth, DB, memory |
| `olav-netops` | `olav-netops/` | Network domain extension (OpenConfig, topology, CLAB, collectors) |
| `olav-ent` | `olav-ent/` | Enterprise extension (enterprise auth, compliance, governance) |
| `olav-doc` | `olav-doc/` | Public docs site (MkDocs Material) — `docs.olavai.com` |
| `olav-web` | `olav-web/` | Marketing website + edge application (Astro + Cloudflare Worker + R2) — `olavai.com` |
| `olav-post` | `olav-post/` | Local-only content archive — never published to any remote |

## Repo Boundary Rules

Governance doc: `dev_docs/99. REPO_BOUNDARY_AND_OWNERSHIP.md`

**Allowed dependency directions:**
- `olav-netops -> olav` (platform contract)
- `olav-ent -> olav` (platform contract)
- `olav-doc -> none` (no runtime dependency)
- `olav-web -> none` (no runtime dependency)
- `olav-post -> none` (no runtime dependency, local-only)

**Reverse coupling** (`olav -> olav-netops`, `olav -> olav-ent`) is only allowed via:
- Entry-point / plugin discovery (dynamic)
- Guarded optional imports
- Never as a hard startup dependency

**Forbidden:**
- `olav-doc` importing `src/olav` runtime code
- `olav-web` importing `src/olav` runtime code
- `olav-post` importing `src/olav` runtime code
- `olav` core hardcoding network-domain or enterprise-specific semantics
- Dual-source editing of docs/web in both root and `olav-doc`
- Publishing `olav-post` content to any remote (git, PyPI, CDN)

## Ownership Manifest

**Single source of truth:** `ownership_manifest.yaml` at repo root.

Every path in the repo is covered by a rule with:
- `owner`: which delivery unit owns it
- `class`: asset category (platform, netops, enterprise, docs, etc.)
- `status`: authoritative / transitional / externalized / misplaced / generated
- `git`: track / ignore / secret

**Key commands:**
```bash
# Scan all paths against manifest — should be 0 ERROR
uv run python scripts/scan_ownership.py --summary

# Show only warnings and errors
uv run python scripts/scan_ownership.py --errors-only

# Regenerate .gitignore from manifest (NEVER edit .gitignore manually)
uv run python scripts/gen_gitignore.py --write
```

## .gitignore is Generated

`.gitignore` is **auto-generated** from `ownership_manifest.yaml`. Do not edit it manually.

When you add a new path or change a rule's `git` field in the manifest, run:
```bash
uv run python scripts/gen_gitignore.py --write
```

The `git` field on each manifest rule controls tracking:
- `git: track` — committed to this repo
- `git: ignore` — on disk for dev, not committed
- `git: secret` — never committed (credentials, env files)

File-type patterns (`*.pyc`, `*.so`, etc.) are in the manifest's `gitignore_file_patterns` section.

## olav-doc is the Authoritative Docs Source

As of 2026-04-04, `olav-doc/` is the **sole authoritative source** for:
- `docs/` — MkDocs documentation content
- `mkdocs.yml` — MkDocs configuration

Root `docs/`, `web/`, `mkdocs.yml` have been removed. Do not recreate them.
`olav-doc/web/` has been removed — the marketing website is now in `olav-web/`.

## olav-web is the Target Website Source

`olav-web/` (monorepo subdir, co-located with `olav-netops` and `olav-ent`) is the **target authoritative source** for:
- Astro marketing website (`olavai.com`)
- Cloudflare Worker edge logic
- R2 asset governance

During the two-phase migration, `olav-doc/web/` and `olav-web/` coexist. Once `olav-web/` is stable, `olav-doc/web/` will be removed per the migration rules in `dev_docs/25.WEB_REPO_SPLIT_AND_CLOUDFLARE_ARCHITECTURE.md`.

## Workspace Layout

`.olav/workspace/` is the runtime workspace control plane:

| Path | Owner | Status |
|---|---|---|
| `.olav/workspace/core/` | olav | authoritative (platform agent) |
| `.olav/workspace/config/` | olav | authoritative (platform agent) |
| `.olav/workspace/ops/` | olav-netops | transitional (vendored, will migrate to olav-netops) |
| `.olav/workspace/ops-lab/` | olav-netops | transitional (vendored, will migrate to olav-netops) |

`.olav/databases/` and `.olav/logs/` are runtime-generated, never committed.

## Git Tracking Model

`.olav/` uses a **whitelist model** — everything is ignored by default, only these paths are tracked:
- `.olav/config/*.example`
- `.olav/config/schemas/**`
- `.olav/workspace/config/**`
- `.olav/workspace/core/**`

## What Gets Released (tracked in git)

Only platform core source and essential configs:
- `src/olav/**` — platform Python package
- `pyproject.toml` — package metadata
- `README.md`, `LICENSE` — release metadata
- `ownership_manifest.yaml` — boundary governance
- `.olav/config/*.example`, `.olav/config/schemas/**` — config templates
- `.olav/workspace/core/**`, `.olav/workspace/config/**` — platform agents

Everything else (tests, scripts, dev_docs, sub-repos, exports, databases) stays on disk for development but is not in the release.

## Safety

- `--dangerously-skip-permissions` bypasses approval gates for testing only. See `src/olav/platform/safety/permissions.py`.
- DuckDB `read_only=True` is a data-integrity constraint and is never bypassed.
- Never mount `/` in a privileged container with `rm -rf` — always mount specific directories and guard empty path variables.
