# Contributing to OLAV

**Version**: v1.0.0  
**Date**: 2026-02-08

Thank you for contributing to OLAV! This document provides guidelines for code style, testing, commit messages, and pull request workflows.

---

## 🎯 Core Principles

Before contributing, please review these principles:

1. **TDD (Test-Driven Development)** - Write failing test → implement → refactor
2. **KISS (Keep It Simple, Stupid)** - Simplest solution that works
3. **Use Native Tools** - Prefer DeepAgents, LangGraph, DuckDB native features
4. **No Redundant Code** - Delete unused code immediately
5. **Real E2E Tests** - Test actual user scenarios, not component existence

**Required Reading**:
- [.github/copilot-instructions.md](.github/copilot-instructions.md) - Development principles
- [docs/reference/QUICK_START_DEVELOPER.md](docs/reference/QUICK_START_DEVELOPER.md) - Development setup

---

## 🚀 Getting Started

### 1. Fork & Clone

```bash
# Fork repository on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/olav.git
cd olav

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL_ORG/olav.git
```

### 2. Setup Development Environment

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Setup environment variables
cp .env.example .env
nano .env  # Add LLM_API_KEY
```

### 3. Create Feature Branch

```bash
# Update main branch
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/my-feature-name
```

**Branch Naming Convention**:
- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring
- `test/description` - Test improvements

---

## 📝 Code Style

### Python Style Guide

**Standard**: PEP 8 + Type Hints + Docstrings

#### Type Hints (Required)

```python
# ✅ GOOD - Type hints for all signatures
def query_database(
    sql: str,
    database: str = "main"
) -> dict[str, Any]:
    """Execute SQL query."""
    pass

# ❌ BAD - No type hints
def query_database(sql, database="main"):
    pass
```

#### Docstrings (Required)

**Format**: Google style

```python
def tool_function(param1: str, param2: int = 0) -> dict[str, Any]:
    """One-line summary.
    
    Longer description explaining what the function does,
    when to use it, and any important behavior.
    
    Args:
        param1: Description of parameter
        param2: Description with default behavior
    
    Returns:
        Dictionary with status, data, and metadata
    
    Raises:
        ValueError: When validation fails
    
    Example:
        >>> result = tool_function("input", param2=10)
        >>> print(result["status"])
        success
    """
    pass
```

#### Imports

**Order**: Standard library → Third-party → Local

```python
# ✅ GOOD - Organized imports
import logging
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from config.logging import logger
from config.paths import DB_MAIN_PATH
from olav.lib.data_gateway import DataGateway

# ❌ BAD - Mixed order
from olav.lib.data_gateway import DataGateway
import logging
import duckdb
from config.paths import DB_MAIN_PATH
```

#### Line Length

**Maximum**: 100 characters (prefer 88 for Black compatibility)

```python
# ✅ GOOD - Within limit
result = gateway.query(
    "SELECT name, ip_address, vendor FROM devices WHERE role = 'core'"
)

# ❌ BAD - Too long
result = gateway.query("SELECT name, ip_address, vendor, model, location, version FROM devices WHERE role = 'core'")
```

### Code Formatting

**Tools**: Ruff (formatter + linter)

```bash
# Format code
uv run ruff format src/ tests/

# Fix linting issues
uv run ruff check src/ tests/ --fix

# Check only (no changes)
uv run ruff check src/ tests/
```

**Note**: Code formatting is optional - not required for PR acceptance. Focus on correctness and tests.

### Type Checking

**Tool**: Pyright

```bash
# Check types
uv run pyright src/

# Check specific file
uv run pyright src/olav/agents/query_agent.py
```

**Note**: Type checking is optional - not required for PR acceptance.

---

## 🧪 Testing Requirements

### Testing Standards

**Required**: All new features must have **Real E2E tests** (not mocks)

**Location**: `tests/e2e/test_real_scenarios.py`

**Principles**:
1. ✅ No mocks for business logic
2. ✅ Test complete user scenarios
3. ✅ Monitor side effects (CLI, database, file I/O)
4. ✅ Validate data correctness

**Example**:
```python
@pytest.mark.asyncio
async def test_my_feature(self):
    """
    User Story: Export devices to CSV without CLI execution
    
    Acceptance Criteria:
    1. Query succeeds
    2. CSV file created
    3. NO CLI commands executed
    4. Data is correct
    """
    cli_tracker = CLICommandTracker()
    
    with cli_tracker:
        result = await orchestrate_query("export devices to csv")
        assert result is not None
    
    # Verify behavior
    cli_tracker.assert_no_commands()
    assert Path("exports/devices.csv").exists()
    
    # Verify data
    df = pd.read_csv("exports/devices.csv")
    assert len(df) > 0
    assert "name" in df.columns
```

### Running Tests

```bash
# Run all E2E tests (required before PR)
uv run pytest tests/e2e/test_real_scenarios.py -v

# Run specific test
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_my_feature -v

# Run with coverage
uv run pytest tests/e2e/test_real_scenarios.py --cov=src/olav --cov-report=html
```

### Test Coverage

**Minimum**: No strict requirement, but tests must validate user scenarios

**Focus**: Quality over quantity - 1 good E2E test > 10 mock-heavy tests

---

## 📋 Commit Messages

### Format

**Pattern**: `<type>(<scope>): <subject>`

**Types**:
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation changes
- `refactor` - Code refactoring (no behavior change)
- `test` - Test additions/improvements
- `chore` - Maintenance (dependencies, config)

**Examples**:
```
feat(agent): add security analysis sub-agent
fix(query): handle empty database results
docs(readme): update installation instructions
refactor(tools): simplify database tool logic
test(e2e): add device export validation test
chore(deps): update deepagents to v0.2.1
```

### Commit Message Body (Optional)

```
feat(agent): add security analysis sub-agent

- Implemented SecurityAgent with vulnerability detection
- Added SKILL.md configuration with security tools
- Registered agent in .olav/OLAV.md
- Added E2E test for CVE detection workflow

Closes #123
```

### Commit Requirements

- ✅ Each commit should be functional (builds and passes tests)
- ✅ Write clear, descriptive commit messages
- ✅ Keep commits focused (one logical change per commit)
- ❌ Avoid "WIP" or "fix tests" commits (squash before PR)

---

## 🔀 Pull Request Workflow

### 1. Create Pull Request

```bash
# Push feature branch to your fork
git push origin feature/my-feature-name

# Create PR on GitHub
# Base: upstream/main ← Head: your-fork/feature/my-feature-name
```

### 2. PR Title & Description

**Title**: Same format as commit messages

```
feat(agent): add security analysis sub-agent
```

**Description Template**:
```markdown
## Summary
Brief description of what this PR does.

## Changes
- Changed item 1
- Changed item 2
- Changed item 3

## Testing
- [ ] E2E tests pass
- [ ] Manual testing performed
- [ ] No regression in existing tests

## Related Issues
Closes #123
Relates to #456
```

### 3. PR Checklist

Before submitting PR, verify:

- [ ] Code follows style guidelines (Ruff formatting optional)
- [ ] All new code has type hints and docstrings
- [ ] E2E tests added for new features
- [ ] All tests pass (`pytest tests/e2e/test_real_scenarios.py -v`)
- [ ] No hardcoded paths/configs (use `config.paths.*`)
- [ ] Commit messages follow convention
- [ ] PR description is clear and complete
- [ ] No unnecessary files (no `__pycache__`, `.pyc`, etc.)

### 4. Code Review Process

**Timeline**: Reviewers will respond within 2-3 business days

**Expectations**:
- Address reviewer comments
- Update PR with requested changes
- Keep discussion professional and constructive

**Approval**: Requires 1+ approvals from maintainers

### 5. Merge

**Strategy**: Squash and merge (default)

Maintainer will squash commits into single commit on main branch.

---

## 🏗️ Development Workflows

### Adding a New SubAgent

**Steps**:
1. Create skill directory: `.olav/skills/my-agent/`
2. Write `SKILL.md` configuration
3. Implement agent: `src/olav/agents/my_agent.py`
4. Implement tools: `src/olav/tools/react_my_category.py`
5. Register in `.olav/OLAV.md`
6. Write E2E test: `tests/e2e/test_real_scenarios.py`
7. Test: `uv run pytest tests/e2e/test_real_scenarios.py -v`
8. Commit and create PR

**Reference**: [SUB_AGENT_DEVELOPMENT_GUIDE.md](docs/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md)

---

### Adding a New Tool

**Steps**:
1. Implement tool function: `src/olav/tools/react_category.py`
2. Add type hints and docstring
3. Register in SKILL.md: `.olav/skills/[agent]/SKILL.md`
4. Write unit test: `tests/unit/test_tools_category.py`
5. Write E2E test: `tests/e2e/test_real_scenarios.py`
6. Test: `uv run pytest tests/ -v`
7. Commit and create PR

**Reference**: [TOOL_DEVELOPMENT_GUIDE.md](docs/reference/TOOL_DEVELOPMENT_GUIDE.md)

---

### Modifying Database Schema

**Steps**:
1. Update schema in: `scripts/init_databases.py`
2. Create migration if needed
3. Update `inspect_schema()` tool if needed
4. Update relevant tests
5. Document changes in commit message
6. Commit and create PR

**Reference**: [DATABASE_GUIDE.md](docs/reference/DATABASE_GUIDE.md)

---

## 📚 Documentation Requirements

### When to Update Documentation

Update documentation when:
- ✅ Adding new features (agents, tools)
- ✅ Changing configuration format
- ✅ Modifying database schema
- ✅ Updating API signatures
- ❌ Minor bug fixes (usually no docs needed)

### Documentation Files

| File | When to Update |
|------|----------------|
| `README.md` | Major features, installation changes |
| `docs/reference/*.md` | Technical implementation changes |
| `.github/copilot-instructions.md` | Development principles, workflows |
| `.olav/skills/*/SKILL.md` | Agent configuration changes |

### Documentation Style

- Use clear, concise language
- Include code examples
- Add diagrams for complex concepts
- Keep files organized (use headers, tables, lists)

---

## 🚫 Anti-Patterns to Avoid

### 1. DO NOT Create Documentation Without Request

```markdown
# ❌ BAD - Unnecessary summary docs
FEATURE_SUMMARY.md
IMPLEMENTATION_REPORT.md
CHANGELOG_DETAILED.md

# ✅ GOOD - Update existing docs only
docs/reference/ARCHITECTURE.md (if architecture changed)
```

### 2. DO NOT Leave Redundant Code

```python
# ❌ BAD - Commented code
# def old_query_function(sql):
#     return conn.execute(sql)

# ✅ GOOD - Delete immediately (Git has history)
```

### 3. DO NOT Use Mock-Heavy Tests

```python
# ❌ BAD - Tests components in isolation
def test_agent_exists():
    agent = create_query_agent()
    assert agent is not None

# ✅ GOOD - Tests real user scenarios
async def test_query_devices():
    result = await orchestrate_query("list all devices")
    assert "router-01" in result
```

### 4. DO NOT Hardcode Configuration

```python
# ❌ BAD - Hardcoded paths
db_path = ".olav/db/main.duckdb"

# ✅ GOOD - Use config constants
from config.paths import DB_MAIN_PATH
db_path = DB_MAIN_PATH
```

---

## 🎓 Learning Resources

### Required Reading
1. [QUICK_START_DEVELOPER.md](docs/reference/QUICK_START_DEVELOPER.md) - Development setup
2. [ARCHITECTURE.md](docs/reference/ARCHITECTURE.md) - System architecture
3. [TESTING_QUICK_REFERENCE.md](docs/reference/TESTING_QUICK_REFERENCE.md) - Testing standards

### Implementation Guides
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](docs/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md) - Build agents
- [SKILL_AUTHORING_GUIDE.md](docs/reference/SKILL_AUTHORING_GUIDE.md) - Write SKILL.md
- [TOOL_DEVELOPMENT_GUIDE.md](docs/reference/TOOL_DEVELOPMENT_GUIDE.md) - Create tools
- [DATABASE_GUIDE.md](docs/reference/DATABASE_GUIDE.md) - Work with DuckDB
- [CONFIGURATION_REFERENCE.md](docs/reference/CONFIGURATION_REFERENCE.md) - Configuration

### Code Examples
- `src/olav/agents/query_agent.py` - Query agent implementation
- `src/olav/tools/react_query.py` - Database tools
- `tests/e2e/test_real_scenarios.py` - Real E2E tests

---

## ❓ Getting Help

### Communication Channels
- **Issues**: GitHub Issues for bug reports and feature requests
- **Discussions**: GitHub Discussions for questions
- **PRs**: Pull request comments for code review

### Asking Questions

**Good Question**:
```
I'm trying to add a new tool for parsing TextFSM templates.

1. I followed TOOL_DEVELOPMENT_GUIDE.md
2. Registered tool in SKILL.md
3. Agent doesn't see the tool

Here's my SKILL.md configuration: [paste]
Here's my tool code: [paste]
Error message: [paste]

What am I missing?
```

**Bad Question**:
```
Tool doesn't work. Help!
```

---

## 📋 Contribution Checklist

Before submitting PR:

### Code Quality
- [ ] Code follows Python style guidelines
- [ ] All functions have type hints
- [ ] All functions have docstrings
- [ ] No hardcoded paths/configs
- [ ] No redundant/commented code

### Testing
- [ ] E2E test added for new feature
- [ ] All tests pass locally
- [ ] No regression in existing tests

### Documentation
- [ ] README.md updated (if needed)
- [ ] Reference docs updated (if needed)
- [ ] Code comments added for complex logic

### Git
- [ ] Commit messages follow convention
- [ ] Branch name follows convention
- [ ] PR description is clear
- [ ] No merge conflicts

### Verification
- [ ] Manual testing performed
- [ ] No `__pycache__` or `.pyc` files
- [ ] `.env` not committed

---

## 🎉 Thank You!

Thank you for contributing to OLAV! Your contributions help make OLAV better for everyone.

**Questions?** Open a GitHub Discussion or comment on your PR.

---

**Version**: v1.0.0 (2026-02-08)  
**Status**: ✅ Production Reference
