# CLI Modernization & Optimization Plan (Session 5)

**Objective**: Modernize OLAV CLI layer, reduce complexity, improve maintainability  
**Estimated Duration**: 8 hours  
**Target Reduction**: ~200-300 lines  
**Overall Goal**: Help reach -40% codebase reduction target

---

## 📊 Current CLI Structure

```
src/olav/cli/ (3,575 lines total)
├── cli_main.py          (1,201 lines) - Main CLI entry point, command handlers
├── session.py           (1,193 lines) - Interactive session management
├── commands/
│   ├── builtin.py       (  491 lines) - Built-in commands (exit, help, etc.)
│   ├── base.py          (   91 lines) - Command base classes
│   └── __init__.py      (    5 lines)
├── display.py           (  466 lines) - Output formatting with Rich
├── input_parser.py      (   88 lines) - User input parsing
└── __init__.py          (   40 lines)
```

**Current Framework**: Typer (modern, type-hinted CLI framework)  
**Output Library**: Rich (for formatted terminal output)

---

## 🔍 Detailed Analysis

### 1. cli_main.py (1,201 lines) - Too Large
**Issues**:
- Single file handling: async streaming, command routing, help display, todo management
- Mixed concerns: CLI logic + agent interaction + output formatting
- Too many @app.command handlers in one file
- Duplicate output formatting (should centralize)

**Candidates for Extraction**:
- `stream_agent_response()` (100+ lines) → Could be in `session.py` or new module
- `_display_todos()` (30 lines) → Should be in `display.py`
- Command handlers could be consolidated

**Potential Reduction**: 150-200 lines via consolidation

### 2. session.py (1,193 lines) - Interactive Session Handler
**Issues**:
- Very large single class: OlavPromptSession
- Mixed concerns: prompt rendering, history management, state tracking
- Possible code duplication with display.py

**Candidates for Extraction**:
- History management → Separate class
- State tracking → Separate class
- Prompt rendering → Consolidate with display.py

**Potential Reduction**: 100-150 lines via refactoring

### 3. commands/builtin.py (491 lines) - Built-in Commands
**Issues**:
- Could consolidate with cli_main.py since Typer groups commands naturally
- Unnecessary abstraction layer

**Potential Reduction**: 50-100 lines via consolidation

### 4. display.py (466 lines) - Output Formatting
**Issues**:
- Some duplication with session.py prompt rendering
- Could extract common Rich formatting patterns

**Potential Reduction**: 30-50 lines via consolidation with session

---

## 🎯 Modernization Strategy (Phase-Based)

### Phase 1: Code Cleanup & Consolidation (Days 1-2)
**Goal**: Remove duplication, consolidate related functionality  
**Target**: -50 to -100 lines

**Tasks**:
1. Move `_display_todos()` from cli_main.py → display.py
2. Consolidate Rich formatting functions from session.py → display.py
3. Merge simple built-in commands from builtin.py → cli_main.py
4. Remove redundant helper functions

### Phase 2: Architecture Optimization (Days 2-3)
**Goal**: Simplify structure, improve separation of concerns  
**Target**: -50 to -100 lines

**Tasks**:
1. Extract history management from OlavPromptSession
2. Extract state management from OlavPromptSession
3. Consolidate prompt rendering logic
4. Remove unused command base classes

### Phase 3: Final Polish (Days 3)
**Goal**: Clean up imports, documentation, edge cases  
**Target**: -50 to -100 lines

**Tasks**:
1. Remove redundant imports
2. Consolidate similar functions
3. Simplify error handling
4. Clean up comments and docstrings

---

## 📋 Implementation Roadmap

### Week 1: Consolidation Phase
- [ ] Analyze session.py in detail (identify consolidation opportunities)
- [ ] Merge builtin.py commands into cli_main.py  
- [ ] Move display functions to display.py
- [ ] Extract history management class
- [ ] Commit: "refactor: Consolidate CLI modules, improve organization"

### Week 2: Optimization Phase  
- [ ] Simplify OlavPromptSession (remove merged functions)
- [ ] Simplify ExpertOrchestrator integration
- [ ] Optimize imports and dependencies
- [ ] Test all CLI commands still work
- [ ] Commit: "refactor: Optimize session management, reduce complexity"

### Week 3: Final Polish
- [ ] Clean up remaining duplication
- [ ] Improve type hints consistency
- [ ] Add brief architectural documentation
- [ ] Verify final line count reduction
- [ ] Commit: "refactor: Final CLI polish, improved documentation"

---

## ✅ Success Criteria

- [ ] All CLI commands work identically to before
- [ ] Code compiles with 100% success
- [ ] Line reduction: 200-300 lines (-5.6% to -8.4%)
- [ ] No new dependencies added
- [ ] All Rich output formatting preserved
- [ ] Interactive mode fully functional
- [ ] Single-query mode fully functional
- [ ] Help system working correctly

---

## 🚀 Expected Outcomes

**Code Quality**:
- Clearer module boundaries
- Less duplication
- Easier to test
- Easier to maintain

**Metrics**:
- cli_main.py: 1,201 → ~900-950 lines (-250-300)
- session.py: 1,193 → ~1,050-1,100 lines (-40-80)
- commands/builtin.py: 491 → 0 lines (consolidated to cli_main)
- display.py: 466 → 500+ lines (receives moved functions)
- **Total**: 3,575 → 3,275-3,350 lines (-225-300 lines)

**Final CLI Achievement**:
- Reach -40% overall codebase reduction target
- Modernized, maintainable CLI structure
- Improved code organization

---

## 📌 Dependencies & Prerequisites

- Python 3.9+
- Typer is already installed
- Rich is already installed
- LangGraph integration stable
- Tool Registry working (from Session 4)

---

## 🔄 Rollback Plan

If issues arise:
1. Each phase creates a separate commit
2. Can revert to any phase commit
3. Git history preserved for analysis
4. No breaking changes to public APs

---

**Status**: Ready to begin Phase 1 - Code Cleanup & Consolidation

