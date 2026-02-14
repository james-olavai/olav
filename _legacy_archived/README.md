# _legacy_archived

Consolidated archive directory for legacy and development documentation.

## Contents

### root_docs (~110 files)
Session reports, diagnostics, implementation plans from all development sessions.
- 97 Markdown files (*.md) - Completion reports, analysis documents
- 7 Log files (*.log, *.txt) - Test output and diagnostics
- 3 Python scripts (*.py) - Debug utilities

**Purpose**: Historical documentation of all development work. Reference only.

### archive_v0_to_v0.11 (11M)
Legacy code and documentation from project versions prior to v0.11.2.

- **deprecated/** - Code marked for removal
- **deprecated_e2e_tests/** - Old test implementations
- **deprecated_skills/** - Previous skill definitions
- **deprecated_tools/** - Old tool implementations
- **docs_v0.8.1, docs_v0.9.6** - Previous documentation versions
- **migration_docs/** - Migration guides from older versions
- **test_scripts/** - Legacy test utilities
- Other historical reports and reference materials

**Purpose**: Historical reference and potential recovery of old code patterns.

### dev_doc_archive (3.8M)
Development documentation and working notes.

- **_archive/** - Older doc snapshots
- **plan/** - Development planning documents
- **reference/** - Technical references
- **slides/** - Presentation slides

**Purpose**: Design documentation, meeting notes, and planning materials.

## Usage

These directories are kept for **reference and historical purposes only**. 

**Do NOT**:
- Use code from here for production
- Import modules from these directories
- Reference deprecated patterns as current best practices

**Do**:
- Reference for understanding historical architecture
- Check migration guides when upgrading old features
- Extract useful examples or patterns carefully

---

**Note**: Active documentation is in [docs/](../docs/) directory.
**Note**: Active development resources are in [.olav/](../.olav/) directory.
**Note**: Clean root directory contains only: README.md, README_ZH.md, pyproject.toml, LICENSE, STRUCTURE.md, CLEANUP_COMPLETE.md, uv.lock
