# OLAV - Project Knowledge Base (v0.10.0+)

**Updated:** 2026-02-28
**Strategy:** Federated Specialists | Skill-Centric | Three-DB Isolation

## 1. CORE ARCHITECTURE

OLAV has shifted from a monolithic script collection to a **Federated Specialist Architecture**.

### The "Three-Layer" Truth
1.  **Config SSOT**: ALL settings must come from `src/olav/core/config.py`. Abandon root `config/` directory.
2.  **Agent SSOT**: ALL agent definitions reside in `.olav/workspace/`. Abandon `.olav/skills/`.
3.  **Storage SSOT**:
    *   `olav.duckdb`: Structured network state (Inventory, Routing).
    *   `memory.lancedb`: Dynamic Agent LTM (Facts, Preferences).
    *   `knowledge.lancedb`: Static Knowledge Base (Docs, Manuals).

## 2. DIRECTORY CONVENTION

```
./
├── src/olav/           # Core Framework (Logic, Models, Middlewares)
│   ├── agents/         # Generic Agent orchestrators
│   ├── core/           # Universal truth: config, llm, database
│   └── knowledge/      # KB Engine (Embeddings, Chunking)
├── .olav/              # Runtime Environment
│   ├── workspace/      # Agent & Skill definitions (AGENT.md, SKILL.md)
│   ├── scripts/        # Implementation scripts (Atomic, stdin/stdout)
│   └── databases/      # DuckDB + LanceDB instances
└── dev_docs/          # Architectural decisions and issues log
```

## 3. ANTI-PATTERNS (CRITICAL)

- **❌ NO Legacy Config**: Never import from root `config/`. Use `from olav.core.config import settings`.
- **❌ NO Legacy Skills**: Never reference `.olav/skills/`. All agents are in `.olav/workspace/`.
- **❌ NO Logic in Scripts**: `.olav/scripts/` should be thin wrappers. Move complex logic to `src/olav/core/`.
- **❌ NO Hardcoded Paths**: Use `PathsConfig` from `core.config`.
- **❌ NO Mixed Data**: Keep KB (LanceDB), Memory (LanceDB), and State (DuckDB) in their designated engines.

## 4. DEVELOPMENT WORKFLOW

1.  **Fix Config First**: If a setting is missing, add it to `src/olav/core/config.py`.
2.  **Define in Workspace**: Create/Update `AGENT.md` in `.olav/workspace/<name>/`.
3.  **Implement in Scripts**: Add atomic Python scripts to `.olav/scripts/`.
4.  **Verify via CLI**: Use `uv run olav admin status` to check registry health.

## 5. REASONING: WHY AGENTS FAIL
Agents often default to legacy patterns because:
1.  **Outdated Documentation**: Files like `AGENTS.md` or `OLAV.md` point to old structures.
2.  **Directory Shadows**: The coexistence of `config/` and `src/olav/core/config.py` creates ambiguity.
3.  **Convention Drift**: Mixed usage of "Skills" vs "Workspace" terminology in various subdirectories.

**Action**: Always check `dev_docs/issues.md` for active architectural pivots before starting a task.
