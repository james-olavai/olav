# Code Quality Audit v0.10.1 - Hardcoded Prompts & Caching Analysis

**Date**: 2026-02-06  
**Status**: 📋 Work-In-Progress Audit  
**Scope**: Hardcoded prompts removal, CLI agent caching, SubAgent skill-based loading

---

## Executive Summary

This audit identifies three categories of technical debt in the v0.10.1 codebase:

1. **Hardcoded Prompts in Agent Core** - Dynamic prompt construction in `analyzer.py`, `textfsm_agent.py`, and `agent.py`
2. **Missing Caching for CLI SubAgent** - CLI executor lacks prompt-level caching (unlike query agent)
3. **Fallback Mechanisms in SubAgent Loader** - Legacy hardcoded prompt generators that should be removed

**Impact**: Code duplication, prompt version control issues, inconsistent agent initialization

---

## 1️⃣ Hardcoded Prompts Inventory

### 1.1 analyzer.py - Dynamic Prompt Construction

**Location**: [src/olav/agents/analyzer.py](src/olav/agents/analyzer.py#L316-L380)  
**Function**: `_build_analysis_prompt(state: AnalyzerState) -> str`

```python
# Lines 316-380: Constructs prompt dynamically with:
prompt_parts = [
    "You are a Network Analysis Specialist providing expert insights.",
    "",
    "Data Sources:",
]
# - Similar historical cases (dynamic, agentic learning)
# - DB data (dynamic results)
# - CLI data (dynamic CLI output)
# - Task instructions (static)
```

**Problem**: 
- Task instructions ("Your task: 1. Analyze the data sources...") are hardcoded
- Should move static portions to `.olav/skills/network-analysis/SKILL.md`
- Dynamic portions (historical cases, DB results) should stay in code

**Recommendation**: 
- Extract static task instructions to `prompts.analysis_task` in SKILL.md
- Keep dynamic data assembly in code
- Load template from SKILL.md, inject dynamic content at runtime

---

### 1.2 textfsm_agent.py - Multiple Hardcoded Prompts

**Location**: [src/olav/agents/textfsm_agent.py](src/olav/agents/textfsm_agent.py#L234-L290)

#### 1.2.1 Generation Prompt
```python
# Lines 234-280: _build_generation_prompt()
prompt = f"""You are a TextFSM template expert for network command outputs.

Generate a TextFSM template to parse the following command output:
...
"""
```

**Problem**: Entire prompt hardcoded with:
- Expert role definition
- Requirements (Use `Value`, `List`, `Filldown`, etc.)
- Output format instructions
- Example template structure

**Should move to**: `.olav/skills/textfsm-generator/SKILL.md` → `prompts.generation`

---

#### 1.2.2 Analysis Prompt
**Location**: [src/olav/agents/textfsm_agent.py](src/olav/agents/textfsm_agent.py#L360+)  
**Function**: `_build_analysis_prompt(template: str, test_results: dict, raw_output: str) -> str`

**Problem**: Hardcoded analysis instructions for template improvement

**Should move to**: `.olav/skills/textfsm-generator/SKILL.md` → `prompts.analysis`

---

### 1.3 agent.py - Base Prompt Fallback

**Location**: [src/olav/agent.py](src/olav/agent.py#L81-L120)

```python
# Lines 81-120: create_olav_agent()
if olav_md_path.exists():
    base_prompt = olav_md_path.read_text(encoding="utf-8")
else:
    # P1: Optimized compact system prompt (~500 tokens vs ~3000)
    base_prompt = """# OLAV - Network AI Assistant

You are OLAV, an AI for network operations. Execute queries efficiently.
...
"""
```

**Problem**: 
- Fallback hardcoded prompt (~30 lines)
- Duplicate of OLAV.md content
- Should require OLAV.md to exist (no fallback)

**Recommendation**: Remove fallback, require OLAV.md

---

### 1.4 subagent_loader.py - Fallback Prompt Generator

**Location**: [src/olav/core/subagent_loader.py](src/olav/core/subagent_loader.py#L335-L350)

```python
def _generate_default_prompt(config: dict[str, Any]) -> str:
    """Generate default system prompt from config."""
    name = config.get("name", "agent")
    description = config.get("description", "specialist agent")
    
    prompt = f"You are a {description}.\n\n"
    if capabilities:
        prompt += "Your capabilities:\n"
        for cap in capabilities:
            prompt += f"- {cap}\n"
    
    return prompt.strip()
```

**Problem**: 
- Generic fallback prompt (violation of skill-centric architecture)
- Used when SKILL.md not found or `agent_skill` not specified
- Should enforce loading from SKILL.md or fail clearly

---

## 2️⃣ CLI Agent Caching Analysis

### 2.1 Current State

**CLI SubAgent Definition**: [.olav/OLAV.md](/.olav/OLAV.md#L51-L62)
```yaml
### cli
name: cli
agent_skill: network-cli
description: CLI command execution specialist for network operations
```

**SKILL.md**: [.olav/skills/network-cli/SKILL.md](/.olav/skills/network-cli/SKILL.md)
- ✅ Has `prompts.system` in frontmatter
- ✅ Proper tools list (nornir_execute, query_database, list_devices)
- ❓ No caching configuration

### 2.2 Caching Mechanism

**Query Agent Caching**: [src/olav/agents/query_agent.py](src/olav/agents/query_agent.py#L160-L170)
```python
# Line 160+: Uses LangChain's chat model with implicit caching
from deepagents import DeepAgent  # Auto-applies caching

self.agent = DeepAgent(model=model, system_prompt=..., tools=...)
```

**CLI SubAgent Caching**: Via DeepAgents SubAgent middleware
- SubAgents inherit caching from orchestrator's LLM instance
- But: No explicit caching configuration in SKILL.md
- Current: Relies on default DeepAgents caching (should be verified)

### 2.3 What's Missing

❓ **Questions to Verify**:
1. Does CLI SubAgent use standard DeepAgents framework? → YES (in orchestrator.py)
2. Is caching enabled? → IMPLICIT (needs explicit configuration)
3. Cache key strategy? → Uses LLM prompt hash (default)

**Recommendation**: Add explicit caching configuration to network-cli SKILL.md

---

## 3️⃣ SubAgent Skill-Based Loading Audit

### 3.1 SubAgent Configuration Flow

```
OLAV.md (SubAgent Registry)
    ↓
subagent_loader.py:load_subagents_from_olav()
    ↓
_load_from_skill(skill_name, agent_name)
    ↓
.olav/skills/{skill_name}/SKILL.md (system prompt + tools)
    ↓
Orchestrator → DeepAgent SubAgent
```

### 3.2 Current Implementation

**Location**: [src/olav/core/subagent_loader.py](src/olav/core/subagent_loader.py#L173-L210)

```python
def _load_from_skill(skill_name: str, agent_name: str) -> tuple[str, list[Any]]:
    """Load system prompt and tools from agent's SKILL.md file."""
    
    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"
    
    if not skill_path.exists():
        # PROBLEM: Fallback to hardcoded
        return _generate_default_prompt(...), _resolve_legacy_tools(agent_name)
    
    try:
        loader = get_skill_loader()
        skill = loader.get_skill(skill_name)
        
        if not skill:
            # PROBLEM: Another fallback
            return _generate_default_prompt(...), _resolve_legacy_tools(agent_name)
        
        # ✅ Extract system prompt from SKILL.md frontmatter
        system_prompt = skill.frontmatter.get("prompts", {}).get("system", "")
```

### 3.3 Problems Identified

| Issue | Severity | Location | Impact |
|-------|----------|----------|--------|
| Fallback 1: Missing SKILL.md | 🔴 HIGH | Line 209 | Silent degradation if skill file missing |
| Fallback 2: Skill not found | 🔴 HIGH | Line 214 | Loader error becomes hidden |
| Generic prompt generator | 🟠 MEDIUM | Line 335 | Violates skill-centric principle |
| Legacy tool resolver | 🟠 MEDIUM | Line 364 | Old agent discovery pattern |

### 3.4 Verification Checklist

✅ **Currently Using Skills**:
- network-query with prompts.system
- network-cli with prompts.system
- network-analysis with prompts.system
- orchestrator with prompts.system
- network-expert with prompts.system
- network-inspection with prompts.system

❌ **Missing Prompts in Skills**:
- textfsm-generator: NO `prompts.generation`, `prompts.analysis`
- guard: Not audited yet

---

## 4️⃣ Recommendations by Priority

### Priority 1: Remove Fallback Mechanisms (Breaking Change)

**Action**: Clean subagent_loader.py like network-cli blacklist refactoring

```python
# REMOVE these fallback functions:
def _generate_default_prompt(config: dict[str, Any]) -> str:  # DELETE
    """Generate default system prompt from config."""
    ...

def _resolve_legacy_tools(agent_name: str) -> list[Any]:  # DELETE
    """Resolve tools using legacy module-based approach."""
    ...

# CHANGE: Enforce skill.md loading
if not skill:
    raise ValueError(
        f"Skill '{skill_name}' not found. "
        f"Required: .olav/skills/{skill_name}/SKILL.md with prompts.system"
    )
```

**Breaking Change**:
- All SubAgents MUST have SKILL.md with prompts.system
- No more generic fallback prompts
- Clear error if skill not found

---

### Priority 2: Move Hardcoded Prompts to Skills

**Target Files**:
1. `textfsm_agent.py`: Move `_build_generation_prompt()` + `_build_analysis_prompt()` prompts to `.olav/skills/textfsm-generator/SKILL.md`
   - Add `prompts.generation` section
   - Add `prompts.analysis` section

2. `analyzer.py`: Move task instructions to `.olav/skills/network-analysis/SKILL.md`
   - Add `prompts.analysis_task` section
   - Keep dynamic case/data assembly in code

3. `agent.py`: Remove fallback `base_prompt` (require OLAV.md always)

---

### Priority 3: Enable Explicit Caching for CLI

**Add to `.olav/skills/network-cli/SKILL.md`**:

```yaml
caching:
  enabled: true
  strategy: prompt_hash
  ttl_seconds: 3600
  key_fields: [command, device]  # Cache key composition
```

---

### Priority 4: Add Missing Prompts to textfsm-generator

**Add to `.olav/skills/textfsm-generator/SKILL.md`**:

```yaml
prompts:
  generation: |
    You are a TextFSM template expert...
    [move from textfsm_agent._build_generation_prompt()]
    
  analysis: |
    You are a TextFSM template optimizer...
    [move from textfsm_agent._build_analysis_prompt()]
```

---

## 5️⃣ Implementation Plan

### Phase 1: Enforce Skill-Centric Loading (Risk: BREAKING)
- Remove fallback functions from subagent_loader.py
- Test all SubAgents load successfully
- Update error messages to guide users

### Phase 2: Move Hardcoded Prompts
- Extract prompts from agent files
- Add to respective SKILL.md files
- Update agent code to load from SKILL.md
- Test prompt behavior unchanged

### Phase 3: Enable Caching Configuration
- Add `caching` section to network-cli SKILL.md
- Verify DeepAgents SubAgent respects config
- Add cache metrics to orchestrator

### Phase 4: Cleanup
- Remove unused prompt builder functions
- Verify all E2E tests pass
- Update documentation

---

## Files Affected

| File | Issue | Action | Priority |
|------|-------|--------|----------|
| src/olav/core/subagent_loader.py | Fallback mechanisms | Remove (P1) | 🔴 HIGH |
| src/olav/agents/analyzer.py | Hardcoded task prompt | Move to SKILL.md (P2) | 🟠 MED |
| src/olav/agents/textfsm_agent.py | 2 hardcoded prompts | Move to SKILL.md (P2) | 🟠 MED |
| src/olav/agent.py | Fallback base_prompt | Remove (P2) | 🟠 MED |
| .olav/skills/network-cli/SKILL.md | No caching config | Add config (P3) | 🟡 LOW |
| .olav/skills/textfsm-generator/SKILL.md | Missing prompts | Add prompts (P4) | 🟡 LOW |

---

## Audit Sign-Off

- **Status**: 📋 AUDIT COMPLETE - Work Plan Ready
- **Code Freeze**: Ready for Phase 1 implementation
- **Risk Level**: MEDIUM (breaking changes in Phase 1)
- **Timeline**: 3 phases, estimated 4-6 hours

