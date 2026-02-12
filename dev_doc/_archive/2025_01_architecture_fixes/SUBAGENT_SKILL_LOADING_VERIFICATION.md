# SubAgent Skill-Based Loading Verification Report

**Date**: 2026-02-06  
**Focus**: Task 4 - Verify all SubAgents load through SKILL.md, not hardcoded

---

## Executive Summary

✅ **SubAgent Framework is Skill-Based**: All SubAgent configurations are loaded from `.olav/OLAV.md` and delegate to `.olav/skills/*/SKILL.md` files.

However, ⚠️ **Fallback Mechanisms Exist**: Code still has generic fallback prompt generator and legacy tool resolver that can hide configuration issues.

---

## 1️⃣ Skill-Based Loading Flow Verification

### 1.1 Configuration Path

```
User Input
    ↓
Orchestrator.create_orchestrator()
    ↓
load_subagents_from_olav()
    ├─ Read .olav/OLAV.md
    ├─ Extract "## SubAgent Registry" section
    └─ Parse each ### agent_name block
        ↓
    _build_subagent(config)
        ├─ Get agent_skill from config
        └─ _load_from_skill(skill_name, agent_name)
            ├─ Find .olav/skills/{skill_name}/SKILL.md
            └─ Extract prompts.system
                ↓
            Create SubAgent instance
```

### 1.2 Each SubAgent's Skill Loading

**Query SubAgent** ✅
```
OLAV.md: agent_skill: network-query
    ↓
.olav/skills/network-query/SKILL.md
    ├─ prompts.system: ✅ YES
    └─ tools: [query_database, inspect_schema, discover_data]
```

**CLI SubAgent** ✅
```
OLAV.md: agent_skill: network-cli
    ↓
.olav/skills/network-cli/SKILL.md
    ├─ prompts.system: ✅ YES
    └─ tools: [nornir_execute, query_database, list_devices]
```

**Analysis SubAgent** ✅
```
OLAV.md: agent_skill: network-analysis
    ↓
.olav/skills/network-analysis/SKILL.md
    ├─ prompts.system: ✅ YES
    └─ tools: [analyze_network, query_database, nornir_execute]
```

**Expert SubAgent** ✅
```
OLAV.md: agent_skill: network-expert
    ↓
.olav/skills/network-expert/SKILL.md
    ├─ prompts.system: ✅ YES
    └─ tools: [Complex expert tools]
```

**Inspection SubAgent** ✅
```
OLAV.md: agent_skill: network-inspection
    ↓
.olav/skills/network-inspection/SKILL.md
    ├─ prompts.system: ✅ YES
    └─ tools: [Multi-layer health checks]
```

### 1.3 Current Implementation Status

**Location**: [src/olav/core/subagent_loader.py](src/olav/core/subagent_loader.py#L40-L80)

```python
def load_subagents_from_olav(olav_path: Path | None = None) -> list[SubAgent]:
    """Load SubAgent configurations from OLAV.md."""
    
    if olav_path is None:
        olav_path = Path(PROJECT_ROOT) / ".olav" / "OLAV.md"
    
    if not olav_path.exists():
        raise FileNotFoundError(f"OLAV.md not found: {olav_path}")
    
    # Extract SubAgent section
    subagent_section = _extract_subagent_section(content)
    
    # Parse individual SubAgent configs
    subagent_configs = _parse_subagent_configs(subagent_section)
    
    # Build SubAgent instances
    subagents = []
    for config in subagent_configs:
        if not config.get("enabled", True):
            continue
        
        subagent = _build_subagent(config)  # ← Loads from SKILL.md
        subagents.append(subagent)
    
    return subagents
```

**Result**: ✅ **All SubAgents load through SKILL.md**

---

## 2️⃣ Fallback Mechanisms (Code Smell)

### 2.1 Fallback 1: Missing SKILL.md File

**Location**: [src/olav/core/subagent_loader.py](src/olav/core/subagent_loader.py#L205-L210)

```python
def _load_from_skill(skill_name: str, agent_name: str) -> tuple[str, list[Any]]:
    """Load system prompt and tools from agent's SKILL.md file."""
    
    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"
    
    if not skill_path.exists():
        # 🔴 PROBLEM: Silently falls back
        return _generate_default_prompt({"name": agent_name}), \
               _resolve_legacy_tools(agent_name)
```

**Impact**: If SKILL.md doesn't exist, gets generic fallback prompt instead of failing clearly.

### 2.2 Fallback 2: Skill Loader Returns None

**Location**: [src/olav/core/subagent_loader.py](src/olav/core/subagent_loader.py#L216-L220)

```python
loader = get_skill_loader()
skill = loader.get_skill(skill_name)

if not skill:
    # 🔴 PROBLEM: Loader error becomes hidden
    logger.warning(f"Skill '{skill_name}' not found in loader, using fallback")
    return _generate_default_prompt({"name": agent_name}), \
           _resolve_legacy_tools(agent_name)
```

**Impact**: Skip error investigation, mask loader issues.

### 2.3 Fallback 3: Generic Prompt Generator

**Location**: [src/olav/core/subagent_loader.py](src/olav/core/subagent_loader.py#L335-L350)

```python
def _generate_default_prompt(config: dict[str, Any]) -> str:
    """Generate default system prompt from config."""
    name = config.get("name", "agent")
    description = config.get("description", "specialist agent")
    capabilities = config.get("capabilities", [])
    
    prompt = f"You are a {description}.\n\n"
    
    if capabilities:
        prompt += "Your capabilities:\n"
        for cap in capabilities:
            prompt += f"- {cap}\n"
    
    return prompt.strip()
```

**Problem**: 
- Generic fallback (violates skill-centric architecture)
- Produces lame prompts like: "You are a specialist agent.\n\n"
- No domain expertise, no proper instructions

### 2.4 Fallback 4: Legacy Tool Resolver

**Location**: [src/olav/core/subagent_loader.py](src/olav/core/subagent_loader.py#L355-L395)

```python
def _resolve_legacy_tools(agent_name: str) -> list[Any]:
    """Resolve tools using legacy module-based approach."""
    
    if agent_name == "query":
        from olav.tools.react_query import query_database, inspect_schema, discover_data
        return [query_database, inspect_schema, discover_data]
    
    elif agent_name == "cli":
        # 🟠 LEGACY: Hardcoded tool list (should be in SKILL.md)
        from olav.tools.network import list_devices, nornir_execute
        from olav.tools.react_query import query_database, inspect_schema
        return [nornir_execute, list_devices, query_database, inspect_schema]
    
    # ... more legacy implementations
    return []
```

**Problem**: 
- Old-style hardcoded tool discovery
- Duplicate of SKILL.md tool definitions
- Masks when SKILL.md is misconfigured

---

## 3️⃣ Orchestrator System Prompt Loading

### 3.1 Current Implementation

**Location**: [src/olav/agents/orchestrator.py](src/olav/agents/orchestrator.py#L119-L145)

```python
# Load system prompt from SKILL.md (v0.10.0+ Skill-Centric Architecture)
from olav.core.skill_loader import get_skill_loader

loader = get_skill_loader()
orchestrator_skill = loader.get_skill("orchestrator")

if orchestrator_skill and orchestrator_skill.content:
    # Extract system prompt from markdown content (after frontmatter)
    content_lines = orchestrator_skill.content.split('\n')
    
    # Find where frontmatter ends
    fm_end = 0
    count = 0
    for i, line in enumerate(content_lines):
        if line.strip() == '---':
            count += 1
            if count == 2:
                fm_end = i + 1
                break
    
    # Use markdown content as system prompt
    system_prompt = '\n'.join(content_lines[fm_end:]).strip()
else:
    # 🔴 PROBLEM: Fails here if SKILL.md missing
    raise ValueError(
        "Orchestrator SKILL.md not found or empty at .olav/skills/orchestrator/SKILL.md. "
        "This file is required for Skill-Centric Architecture."
    )
```

**Result**: ✅ **Orchestrator correctly enforces SKILL.md** (no fallback, crashes if missing)

---

## 4️⃣ SubAgent Skill Loading - What Works vs What Doesn't

### ✅ What Works (Skill-Centric)

1. **SubAgent Registry** (.olav/OLAV.md)
   - Declarative configuration for each SubAgent
   - No hardcoded SubAgent list
   - Can add new SubAgents without code changes

2. **Skill File Loading** (.olav/skills/*/SKILL.md)
   - System prompts loaded from frontmatter
   - Tools list loaded from frontmatter
   - Version control friendly

3. **Orchestrator System Prompt**
   - Fully loaded from .olav/skills/orchestrator/SKILL.md
   - No hardcoded orchestrator prompt
   - Clear error if SKILL.md missing

### ❌ What Doesn't (Still Hardcoded/Fallback)

1. **SubAgent Prompts**
   - Fallback generic prompt if SKILL.md missing
   - _generate_default_prompt() is hardcoded
   - Users don't know configuration is degraded

2. **SubAgent Tools**
   - Fallback legacy tool resolver if SKILL.md missing
   - _resolve_legacy_tools() has hardcoded tool lists
   - Perpetuates old discovery pattern

3. **Error Handling**
   - Warnings instead of errors when SKILL.md not found
   - Masks configuration problems
   - "Works" with degraded functionality

---

## 5️⃣ Comparison: Orchestrator vs SubAgents

| Aspect | Orchestrator | SubAgents |
|--------|--------------|-----------|
| Config Source | SKILL.md | SKILL.md ✅ |
| Missing SKILL.md | ❌ FAILS clearly | ✅ Silently falls back ⚠️ |
| System Prompt | From markdown content | From `prompts.system` ✅ |
| Tools | Hardcoded | From SKILL.md ✅ |
| Fallback Logic | None | _generate_default_prompt() + _resolve_legacy_tools() ⚠️ |

---

## 6️⃣ Current SubAgent Readiness

### SubAgent: query ✅ COMPLETE
- SKILL.md: ✅ Has prompts.system
- Tools: ✅ Listed in SKILL.md
- Fallback: N/A (always loads)

### SubAgent: cli ✅ COMPLETE
- SKILL.md: ✅ Has prompts.system
- Tools: ✅ Listed in SKILL.md
- Fallback: Would work but not ideal

### SubAgent: analysis ✅ COMPLETE
- SKILL.md: ✅ Has prompts.system
- Tools: ✅ Listed in SKILL.md
- Fallback: Would work but not ideal

### SubAgent: expert ✅ COMPLETE
- SKILL.md: ✅ Has prompts.system
- Tools: ✅ Listed in SKILL.md
- Fallback: Would work but not ideal

### SubAgent: inspection ✅ COMPLETE
- SKILL.md: ✅ Has prompts.system
- Tools: ✅ Listed in SKILL.md
- Fallback: Would work but not ideal

---

## 7️⃣ Recommendations

### Phase 1: Remove Fallback Mechanisms (BREAKING)

**Action**: Like the network-cli blacklist refactoring

```python
# DELETE these functions:
def _generate_default_prompt(config):  # DELETE
def _resolve_legacy_tools(agent_name):  # DELETE
def _resolve_agent_tools(agent_name):  # DELETE

# CHANGE: Enforce SKILL.md loading
def _load_from_skill(skill_name: str, agent_name: str):
    skill_path = Path(...) / "SKILL.md"
    
    if not skill_path.exists():
        raise ValueError(
            f"Required: .olav/skills/{skill_name}/SKILL.md with "
            f"prompts.system and tools configuration"
        )
    
    loader = get_skill_loader()
    skill = loader.get_skill(skill_name)
    if not skill:
        raise ValueError(f"Failed to load skill {skill_name}")
    
    # Extract system prompt
    system_prompt = skill.frontmatter.get("prompts", {}).get("system", "")
    if not system_prompt:
        raise ValueError(
            f"Skill {skill_name} missing prompts.system in SKILL.md"
        )
    
    # Extract tools
    tools = skill.frontmatter.get("tools", [])
    if not tools:
        logger.warning(f"Skill {skill_name} has no tools configured")
    
    return system_prompt, _hydrate_tools(tools)
```

**Impact**: 
- All SubAgents MUST have properly configured SKILL.md
- Clear errors if configuration incomplete
- No silent degradation

### Phase 2: Verify All SubAgents Work Without Fallback

- Test each SubAgent loads prompts from SKILL.md
- Test each SubAgent loads tools correctly
- No fallback activation

---

## 8️⃣ Sign-Off

- **SubAgent Skill Loading**: ✅ Implemented correctly
- **Orchestrator**: ✅ Enforces SKILL.md (no fallback)
- **SubAgents**: ⚠️ Have fallback mechanisms (should be removed)
- **Recommendation**: Phase 1 - Remove fallback like network-cli

