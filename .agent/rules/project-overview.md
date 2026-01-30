---
trigger: always_on
---

# Development Guidelines

This document contains critical information about working with this codebase. Follow these guidelines precisely.

## Core Development Rules

1. Package Management
   - ONLY use uv, NEVER pip
   - Installation: `uv add package`
   - Running tools: `uv run tool`
   - Upgrading: `uv add --dev package --upgrade-package package`
   - FORBIDDEN: `uv pip install`, `@latest` syntax

2. Code Quality
   - Type hints required for all code
   - Public APIs must have docstrings
   - Functions must be focused and small
   - Follow existing patterns exactly
   - Line length: 88 chars maximum

3. Testing Requirements
   - Framework: `uv run pytest`
   - Async testing: use anyio, not asyncio
   - Coverage: test edge cases and errors
   - New features require tests
   - Bug fixes require regression tests
   - **E2E Testing Strategy**:
     - Use OLAV CLI (`uv run olav`) for validation
     - **Mandatory**: Test with REAL LLM and REAL Devices/Nodes
     - Success standard: `echo "查询" | uv run olav` produces production-ready output
     - Process: Perform manual step-by-step verification of outputs

4. Code Style
    - PEP 8 naming (snake_case for functions/variables)
    - Class names in PascalCase
    - Constants in UPPER_SNAKE_CASE
    - Document with docstrings
    - Use f-strings for formatting

- For commits fixing bugs or adding features based on user reports add:
  ```bash
  git commit --trailer "Reported-by:<name>"
  ```
  Where `<name>` is the name of the user.

- For commits related to a Github issue, add
  ```bash
  git commit --trailer "Github-Issue:#<number>"
  ```
- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

## E2E Acceptance Testing (CRITICAL)

**验收测试文件**: `tests/00_e2e_acceptance_test.py`

### 开发循环 (Development Loop)

```
修改代码 → uv run pytest tests/00_e2e_acceptance_test.py -v → 失败?
                                                              │
                                    ┌─────────────────────────┴─────────────┐
                                    │ 是                                    │ 否
                                    ▼                                       ▼
                              分析失败原因                              ✅ 提交代码
                              修复代码                                    下一功能
                                    │
                                    └──────→ 重新运行测试
```

### 测试阶段

| 阶段 | 必须通过 | 说明 |
|:---|:---|:---|
| Phase 0 | ✅ | 代码质量 (ruff + pyright + coverage) |
| Phase 1 | ✅ | 环境清理 |
| Phase 2 | ✅ | Snapshot 采集 |
| Phase 3 | ✅ | Exports 目录结构 |
| Phase 4 | ✅ | 数据库结构 |
| Phase 5 | ✅ | ReAct 查询功能 |
| Phase 6 | ✅ | Zero-ETL 查询 |

**全部通过 = 验收完成**

### 代码质量要求

| 检查项 | 命令 | 要求 |
|:---|:---|:---|
| Ruff Lint | `uv run ruff check src/` | 0 errors |
| Ruff Format | `uv run ruff format --check src/` | 0 unformatted |
| Pyright | `uv run pyright src/` | 0 errors (warnings 可接受) |
| Coverage | `uv run pytest --cov=src/olav --cov-fail-under=80` | ≥ 80% |

### 常用测试命令

```bash
# 完整 E2E 测试
uv run pytest tests/00_e2e_acceptance_test.py -v

# 代码质量检查 (必须首先通过)
uv run pytest tests/00_e2e_acceptance_test.py::TestCodeQuality -v

# 单阶段测试
uv run pytest tests/00_e2e_acceptance_test.py::TestPhase5QueryTools -v

# 带覆盖率的完整测试
uv run pytest --cov=src/olav --cov-report=term-missing --cov-fail-under=80

# 快速修复 ruff 问题
uv run ruff check src/ --fix && uv run ruff format src/
```

## Development Philosophy

- **Skill-Centric Design**: The "Skill" (Markdown) is the core unit of capability. Code supports Skills.
  - Skills define **WHAT** tools are available (`tools` field)
  - Scripts implement **HOW** tools work (`.olav/scripts/*.py`)
  - Agents orchestrate **WHEN** to use tools (Platform-specific)

- **Platform-Agnostic Architecture**:
  - **Goal**: `mv .olav .claude` or `mv .olav .gemini` enables seamless migration
  - **Skill Layer**: 100% platform-independent (Markdown + Scripts)
  - **Adapter Layer**: Native `deepagents.SkillsMiddleware` (Specification-compliant)
  - **Agent Layer**: Federated Specialists (1 Agent : 1 Skill)

- **Zero Fallback Strategy**:
  - ❌ **No Progressive Migration**: No `if use_new_*` config switches
  - ✅ **Direct Replacement**: Delete old code, use Git revert for rollback
  - ✅ **Clean Codebase**: No `*_v1.py` and `*_v2.py` coexistence

- **Unified Script Standard**:
  - ❌ **No Native Mode**: Abandoned for simplicity (subprocess overhead ~50-100ms is negligible)
  - ✅ **Script Only**: All tools use `.olav/scripts/*.py` with stdin/stdout
  - ✅ **Standard Template**: All scripts follow the same pattern
  - ✅ **Performance Optimization**: Optional script caching (transparent to users)

- **Universal Compatibility**:
  - Maintain 1:1 directory compatibility with Claude Code (`.olav/` <=> `.claude/`)
  - Ensure architecture is compatible with other Agent frameworks

- **Simplicity**: Write simple, straightforward code
- **Readability**: Make code easy to understand
- **Performance**: Consider performance without sacrificing readability
- **Maintainability**: Write code that's easy to update
- **Testability**: Ensure code is testable
- **Reusability**: Create reusable components and functions
- **Less Code = Less Debt**: Minimize code footprint

## Coding Best Practices

- **Early Returns**: Use to avoid nested conditions
- **Descriptive Names**: Use clear variable/function names (prefix handlers with "handle")
- **Constants Over Functions**: Use constants where possible
- **DRY Code**: Don't repeat yourself
- **Functional Style**: Prefer functional, immutable approaches when not verbose
- **Minimal Changes**: Only modify code related to the task at hand
- **Function Ordering**: Define composing functions before their components
- **TODO Comments**: Mark issues in existing code with "TODO:" prefix
- **Simplicity**: Prioritize simplicity and readability over clever solutions
- **Build Iteratively** Start with minimal functionality and verify it works before adding complexity
- **Run Tests**: Test your code frequently with realistic inputs and validate outputs
- **Build Test Environments**: Create testing environments for components that are difficult to validate directly
- **Functional Code**: Use functional and stateless approaches where they improve clarity
- **Clean logic**: Keep core logic clean and push implementation details to the edges
- **File Organsiation**: Balance file organization with simplicity - use an appropriate number of files for the project scale

OLAV v0.10.0 follows the **Skill-Centric Platform-Agnostic Architecture**:

### Three-Layer Architecture (Olav v0.10.0+)

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Skill Layer (Platform-Agnostic)               │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ .olav/skills/*.md                                   │ │
│ │ - 符合 agentskills.io 规范                           │ │
│ │ - 必须定义 parameters JSON Schema                    │ │
│ └─────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ .olav/scripts/*.py                                  │ │
│ │ - 独立可运行脚本 (stdin/stdout)                      │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Middleware Layer (Native DeepAgents)           │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│ │SkillsMiddleware│ │ MemoryMiddleware││  Filesystem...│  │
│ │ (Spec Parser)  │ │ (Context)      ││  (Sandboxing)  │  │
│ └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Layer 3: Federated Agent Layer (Specialists)           │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│ │Routing Agent │  │Switching Agent│  │ Security Agent│  │
│ │(1 Agent:1 Sk)│  │(1 Agent:1 Sk)│  │(1 Agent:1 Sk)│  │
│ └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Hybrid Agent Strategy (Performance Critical)

OLAV v0.10.0 adopts a **Hybrid Agent Architecture** to balance speed and intelligence. ReAct loops (DeepAgents) are expensive (50s+ latency) and should ONLY be used for complex analysis.

| Tier | Component | Architecture | Latency | Use Case |
|:---|:---|:---|:---|:---|
| **Tier 0** | **Semantic Cache** | Vector Search | **<0.5s** | High-frequency repeated queries |
| **Tier 1** | **Standard Agents** | **Zero-Shot LLM** (No ReAct Loop) | **3-5s** | SQL Gen, CLI Commands, Routing |
| **Tier 2** | **Analysis Agent** | **DeepAgents ReAct** (Full Middleware) | **30s+** | Root Cause Analysis, Multi-step Diagnosis |

**Implementation Rules**:
1. **Tier 1 (Standard)**:
   - Use `create_deep_agent` but **DISABLE** middleware and tools.
   - Force **Max Iterations = 1**.
   - Prompt: "You are a translator. Output only the SQL/JSON. Do not think."
   
2. **Tier 2 (Analysis)**:
   - Use full `create_deep_agent` with tools and middleware.
   - Enable "Thinking" and self-correction.

3. **Routing**:
   - Router MUST prioritize Tier 0 -> Tier 1.
   - Only route to Tier 2 if user explicitly asks for "Analysis" or "Troubleshoot".

### Data Flow

```
用户输入
    ↓
规则 Guard (正则匹配, 0 延迟)
    ↓ (通过)
Intent Router (LLM, 1 次调用)
    ↓
Skill Execution
    ↓
平台 Adapter (加载 Skill)
    ↓
Script 执行器 (subprocess.run 或 importlib 缓存)
    ↓
Python 脚本 (.olav/scripts/*.py)
    ↓
输出 JSON
```

### Runtime

- **DeepAgents/LangChain**: Agent orchestration (Native Skills support)
- **DuckDB**: Vector storage, unified data processing
- **SkillsMiddleware**: Native tool registration from SKILL.md (Spec-compliant)
- **Script Executor**: Unified script execution via subprocess
- **Universal Synthesis**: ALL tool outputs must be formatted via LLM Markdown synthesis

## Core Components

- `src/olav/cli/cli_main.py`: Main entry point (CLI)
- `src/olav/core/skill_adapter.py`: Skill-to-Tool adapter (dynamic registration)
- `src/olav/core/unified_database.py`: DuckDB connection management
- `src/olav/agents/query_agent_v2.py`: Query Agent (Skill-Centric)
- `src/olav/agents/inspector.py`: Inspection Agent (MapReduce)
- `.olav/skills/`: Skill definitions (platform-agnostic)
- `.olav/scripts/`: Tool implementations (platform-agnostic)
- `docs/00_olav_v0.9_roadmap.md`: **Single Source of Truth**

## Core Directories

```
.olav/
├── skills/           # Skill markdown files
├── knowledge/        # Knowledge markdown files
├── db/               # DuckDB databases
└── config/           # Runtime configuration

data/exports/
└── YYYY-MM-DD_HHMMSS/
    ├── raw/          # Raw command outputs
    └── parsed/       # Parsed JSON data

src/olav/
├── cli/              # CLI commands
├── core/             # Core modules (DB, LLM, settings)
└── tools/            # Tool implementations
```

## Pull Requests

- Create a detailed message of what changed. Focus on the high level description of
  the problem it tries to solve, and how it is solved. Don't go into the specifics of the
  code unless it adds clarity.

- Always add `ArthurClune` as reviewer.

- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

## Python Tools

## Code Formatting

1. Ruff
   - Format: `uv run ruff format .`
   - Check: `uv run ruff check .`
   - Fix: `uv run ruff check . --fix`
   - Critical issues:
     - Line length (88 chars)
     - Import sorting (I001)
     - Unused imports
   - Line wrapping:
     - Strings: use parentheses
     - Function calls: multi-line with proper indent
     - Imports: split into multiple lines

2. Type Checking
   - Tool: `uv run pyright`
   - Requirements:
     - Explicit None checks for Optional
     - Type narrowing for strings
     - Version warnings can be ignored if checks pass

3. Pre-commit
   - Config: `.pre-commit-config.yaml`
   - Runs: on git commit
   - Tools: Prettier (YAML/JSON), Ruff (Python)
   - Ruff updates:
     - Check PyPI versions
     - Update config rev
     - Commit config first

## Error Resolution

1. CI Failures
   - Fix order:
     1. Formatting
     2. Type errors
     3. Linting
   - Type errors:
     - Get full line context
     - Check Optional types
     - Add type narrowing
     - Verify function signatures

2. Common Issues
   - Line length:
     - Break strings with parentheses
     - Multi-line function calls
     - Split imports
   - Types:
     - Add None checks
     - Narrow string types
     - Match existing patterns

3. Best Practices
   - Check git status before commits
   - Run formatters before type checks
   - Keep changes minimal
   - Follow existing patterns
   - Document public APIs
   - Test thoroughly