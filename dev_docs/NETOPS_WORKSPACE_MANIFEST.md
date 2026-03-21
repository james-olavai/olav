# NetOps Workspace Asset Manifest

**Purpose:** Documents the workspace assets owned by `olav-netops` that reside in the
monorepo root `.olav/workspace/`. These assets must be migrated to the `olav-netops`
repository when physical repo split is executed (after CORE-1/CORE-2 gate conditions are met).

**Status:** Documented — pending physical migration (migration gate not yet satisfied).

---

## Asset Ownership Table

| Asset Path (monorepo) | Owner Repo | Target Path (post-split) | Description |
|---|---|---|---|
| `.olav/workspace/ops/` | `olav-netops` | `olav-netops/.olav/workspace/ops/` | NetOps ops agent: AGENT.md, MANIFEST.yaml, tools/, prompts/, topology/, probe/, diff/, simulator/ |
| `.olav/workspace/config/sync/` | `olav-netops` | `olav-netops/.olav/workspace/config/sync/` | Config sync skill: snapshot collection, device config sync tools |
| `.olav/workspace/config/learner/` | `olav-netops` | `olav-netops/.olav/workspace/config/learner/` | Config learner skill: field classification learning tools |

---

## Assets Remaining in olav-core

| Asset Path | Owner Repo | Description |
|---|---|---|
| `.olav/workspace/olav/` | `olav-core` | Core platform agent workspace |
| `.olav/workspace/quick/` | `olav-core` | Quick utility agent workspace |
| `.olav/workspace/audit/` | `olav-core` | Audit agent workspace |
| `.olav/workspace/config/discovery/` | `olav-core` | Schema discovery skill (platform-generic) |
| `.olav/workspace/config/creator/` | `olav-core` | Domain agent creator skill |
| `.olav/workspace/config/knowledge/` | `olav-core` | Knowledge base management skill |
| `.olav/workspace/config/system/` | `olav-core` | System configuration skill |

---

## Migration Gate Conditions

Physical migration of the above `olav-netops` assets is blocked until ALL of the following are satisfied:

1. `CORE-1` complete — enterprise imports in `main.py` are conditional.
2. `CORE-2` complete — `tink` and `PyJWT` are in `[project.optional-dependencies] enterprise`.
3. Core platform smoke test + `pytest` full suite passing.
4. Key E2E flows verified against real devices with no regressions.

**Do not execute directory migration until the above gate conditions are confirmed.**

---

## ops/ Workspace Detail

```
.olav/workspace/ops/
├── AGENT.md          — Agent system prompt and role definition
├── MANIFEST.yaml     — Skill registration, slash commands, entry points
├── tools/            — LangChain tool modules (ping, traceroute, port_scan, etc.)
├── prompts/          — Prompt templates
├── topology/         — Topology diff and visualization tools
├── probe/            — Active probing tools
├── diff/             — Configuration diff tools
└── simulator/        — Network simulation tools (LLM sandbox)
```

## config/sync/ Workspace Detail

```
.olav/workspace/config/sync/
└── tools/
    ├── take_snapshot.py     — Device snapshot collection via SSH
    ├── sync_tool.py         — Configuration sync orchestration
    └── ...
```

## config/learner/ Workspace Detail

```
.olav/workspace/config/learner/
└── tools/
    ├── learn_field_mapping.py   — Field classification learning
    └── ...
```
