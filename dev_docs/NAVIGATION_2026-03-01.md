# Navigation Guide: OLAV Architecture Redesign (2026-03-01)

**Today's decisions**: Agent-Driven Onboarding + ReAct Template Generation + TDD Roadmap

---

## 📋 Document Index

### 1. **Architecture & Design** (Read First)
- **[olav_onboard.md](./olav_onboard.md)** — **主文档** (Main Design Document)
  - Complete onboarding architecture redesign
  - Agent-driven flow (Phase 1 Python → Phase 2-7 LLM)
  - 3 critical gaps analysis
  - TDD implementation roadmap (Phase A, B, C)
  - **Start here**: Section 4 (Gap Closure Roadmap) has the most actionable details

### 2. **Integration with Existing Refactor** (Context)
- **[init_refacto.md](./init_refacto.md)** — Onboarding Refactoring Plan
  - Updated to reference new Agent-Driven design
  - DoD checklist aligned with TDD phases
  - Link to olav_onboard.md for complete details

### 3. **Issue Tracking** (Progress)
- **[issues.md](./issues.md)** — Current Known Issues
  - Section 4.1: New "Agent-Driven Onboarding Redesign" issue tracking
  - PR checklist (A1, A2, B1, B2)
  - Links to olav_onboard.md for full implementation plan

### 4. **Session Context**
- **[SESSION_SUMMARY_2026-03-01.md](./SESSION_SUMMARY_2026-03-01.md)** — Prior work (TextFSM generation improvements)
- **[IMPLEMENTATION_COMPLETE.md](./IMPLEMENTATION_COMPLETE.md)** — Completed infrastructure

---

## 🎯 Quick Start: What to Do Next?

### If you're implementing the new onboarding:
1. **Read**: [olav_onboard.md §1-3](./olav_onboard.md#1-architecture-overview)
2. **Understand gaps**: [olav_onboard.md §3](./olav_onboard.md#3-current-state-analysis)
3. **Start TDD**: [olav_onboard.md §5](./olav_onboard.md#5-implementation-roadmap-tdd) — write Phase A tests first
4. **Track progress**: Update [issues.md §4.1](./issues.md#41-onboarding-架构重设计--in-progress)

### If you're reviewing the design:
1. **Overview**: [olav_onboard.md §2](./olav_onboard.md#2-architecture-decisions)
2. **Gap details**: [olav_onboard.md §3](./olav_onboard.md#3-current-state-analysis)
3. **Solutions**: [olav_onboard.md §4](./olav_onboard.md#4-gap-closure-roadmap-tdd)

### If you're setting up TUI integration:
1. **Data flow**: [olav_onboard.md §1.2](./olav_onboard.md#12-data-flow)
2. **Phase 1 boundary**: [olav_onboard.md §6](./olav_onboard.md#6-file-changes-index)
3. **Test examples**: [olav_onboard.md §5](./olav_onboard.md#52-gap-2-orchestrator-onboard-intent-in-systemmd)

---

## 📊 Status & Ownership

| Component | Status | Owned By | Priority |
|---|---|---|---|
| **Architecture Design** | ✅ Complete | Architecture Review | N/A |
| **Phase A (reparse_outputs + SQL)** | 🔴 Not Started | Backend | 🔴 Critical |
| **Phase B (Intent + TUI)** | 🔴 Not Started | Frontend/Agent | 🔴 Critical |
| **Phase C (E2E Tests)** | 🔴 Not Started | QA | 🔴 Critical |

**Timeline**: 3 weeks total (1 week per phase)

---

## 🔗 Key Design Decisions Documented

| Decision | Location | Rationale |
|---|---|---|
| Phase 1 stays Python | [olav_onboard.md §1.1](./olav_onboard.md#11-phase-distribution) | No LLM available yet |
| Incremental execution (gaps only) | [olav_onboard.md §2.2](./olav_onboard.md#决策2增量执行仅修复-gap) | Network efficiency |
| reparse_outputs tool (no SSH) | [olav_onboard.md §4.1](./olav_onboard.md#41-gap-1-new-tool-reparse_outputs) | Template fix validation |
| TUI + preflight JSON | [olav_onboard.md §1.2](./olav_onboard.md#12-data-flow) | State handoff to Agent |

---

## 📌 Critical Reminders

1. **reparse_outputs is NOT optional** — Without it, every template fix requires SSH reconnection
2. **Tests must come first** (TDD) — Phase A must have comprehensive test suite before implementation
3. **Agent intelligence via rules, not code** — Behavioral rules should be in orchestrator.md, not Python
4. **DuckDB as SSOT** — State queries replace Python conditionals

---

## 📚 Related Documentation

- **Architecture Foundation**: [ARCHITECTURE.md](./ARCHITECTURE_MIGRATION_SKILLCENTRIC.md) (if present)
- **Agent System**: [.olav/workspace/config/AGENT.md](../.olav/workspace/config/AGENT.md)
- **Sync Agent Details**: [.olav/workspace/config/sync/SKILL.md](../.olav/workspace/config/sync/SKILL.md)
- **Learner Agent**: [.olav/workspace/config/learner/SKILL.md](../.olav/workspace/config/learner/SKILL.md)

---

**Last Updated**: 2026-03-01  
**Author**: Architecture Review Session  
**Status**: Ready for Implementation
