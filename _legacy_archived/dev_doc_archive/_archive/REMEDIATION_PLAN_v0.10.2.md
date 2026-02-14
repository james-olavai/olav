# Code Quality Remediation Plan v0.10.2 - Unified Fix Strategy

**Date**: 2026-02-06  
**Status**: 📋 AUDIT COMPLETE - Remediation Plan Ready  
**Scope**: Hardcoded prompts, caching, skill-based loading  

---

## Overview: The Three Technical Debts

Based on complete audit of codebase, OLAV v0.10.1 has three interrelated quality issues:

### 1. Hardcoded Prompts (CRITICAL)
Dynamic prompt construction in agent code instead of SKILL.md
- analyzer.py: Task instructions hardcoded
- textfsm_agent.py: Generation + analysis prompts hardcoded
- agent.py: Fallback base_prompt hardcoded

### 2. Caching Configuration Missing (MEDIUM)
CLI agent has implicit caching but no explicit configuration
- Network-cli SKILL.md lacks caching section
- No cache TTL configuration
- No cache metrics

### 3. Fallback Mechanisms (HIGH - Design Violation)
SubAgent loader has generic fallback prompt + tool resolver
- Violates skill-centric architecture
- Hides configuration issues
- Inconsistent with orchestrator's strict enforcement

---

## Unified Remediation Strategy

### Phase 1: Enforce Skill-Centric Architecture (BREAKING)

**Objective**: Remove fallback mechanisms, enforce SKILL.md loading

**Files to Modify**:
1. `src/olav/core/subagent_loader.py` - Remove fallbacks
2. `src/olav/agent.py` - Remove base_prompt fallback

**Changes**:
```python
# DELETE:
def _generate_default_prompt(config: dict[str, Any]) -> str
def _resolve_legacy_tools(agent_name: str) -> list[Any]
def _resolve_agent_tools(agent_name: str) -> list[Any]

# CHANGE: Enforce SKILL.md
def _load_from_skill(skill_name: str, agent_name: str):
    if not skill_path.exists():
        raise ValueError(
            f"Required: .olav/skills/{skill_name}/SKILL.md with "
            f"prompts.system and tools configuration"
        )
    
    if not skill:
        raise ValueError(f"Failed to load skill {skill_name}")
    
    system_prompt = skill.frontmatter.get("prompts", {}).get("system", "")
    if not system_prompt:
        raise ValueError(f"Skill {skill_name} missing prompts.system")
    
    return system_prompt, _hydrate_tools(skill.frontmatter.get("tools", []))

# DELETE: agent.py fallback base_prompt (~30 lines)
# Require OLAV.md always
```

**Testing**:
- ✅ All 5 SubAgents load without fallback
- ✅ SKILL.md missing → clear error
- ✅ prompts.system missing → clear error
- ✅ E2E tests pass

**Impact**: BREAKING - Deployment must have all SKILL.md files + OLAV.md

---

### Phase 2: Consolidate Hardcoded Prompts (MIGRATION)

**Objective**: Move dynamic prompt templates from code to SKILL.md

#### 2.1 textfsm_agent.py → textfsm-generator SKILL.md

```python
# src/olav/agents/textfsm_agent.py - REFACTOR:

async def generate_node(state: TextfsmState):
    # Before: _build_generation_prompt(...)
    
    # After: Load template from SKILL.md
    from olav.core.skill_loader import get_skill_loader
    
    loader = get_skill_loader()
    skill = loader.get_skill("textfsm-generator")
    
    generation_template = skill.frontmatter.get("prompts", {}).get("generation", "")
    
    prompt = generation_template.format(
        command_name=state.command_name,
        platform=state.platform,
        raw_output=state.raw_output[:2000],
    )
```

**Add to `.olav/skills/textfsm-generator/SKILL.md`**:

```yaml
prompts:
  generation: |
    You are a TextFSM template expert for network command outputs.
    
    Generate a TextFSM template to parse the following command output:
    
    Command: {command_name}
    Platform: {platform}
    
    Raw Output:
    ```
    {raw_output}
    ```
    
    TextFSM Template Requirements:
    [... rest of template]
    
  analysis: |
    You are a TextFSM template optimizer...
    [move from _build_analysis_prompt()]
```

**Code Changes**:
- Delete `_build_generation_prompt()` function
- Delete `_build_analysis_prompt()` function  
- Load templates from SKILL.md
- Use string formatting for dynamic content

#### 2.2 analyzer.py → network-analysis SKILL.md

```python
# src/olav/agents/analyzer.py - REFACTOR:

def _build_analysis_prompt(state: AnalyzerState) -> str:
    # Load template from SKILL.md
    from olav.core.skill_loader import get_skill_loader
    
    loader = get_skill_loader()
    skill = loader.get_skill("network-analysis")
    
    task_template = skill.frontmatter.get("prompts", {}).get("analysis_task", "")
    
    # Build dynamic portions
    prompt_parts = [task_template]
    
    # Add dynamic data sections only
    if state.similar_cases:
        prompt_parts.append(_format_similar_cases(state.similar_cases))
    if state.db_data:
        prompt_parts.append(_format_db_data(state.db_data))
    # ... etc
    
    return "\n\n".join(prompt_parts)
```

**Add to `.olav/skills/network-analysis/SKILL.md`**:

```yaml
prompts:
  system: |  # already exists
    You are a Network Analysis Specialist...
  
  analysis_task: |
    # MOVE from analyzer._build_analysis_prompt() lines 347+
    Your task:
    1. Analyze the data sources above
    2. Identify key findings and patterns
    3. Detect any anomalies or issues
    4. Provide actionable recommendations
    
    Format your response as:
    ## Analysis
    [Your analysis here]
    
    ## Recommendations
    - [Recommendation 1]
    - [Recommendation 2]
```

**Code Changes**:
- Extract task_instruction template to SKILL.md
- Keep dynamic case/data building in code
- Load template at runtime, format with data

#### 2.3 agent.py → Remove Fallback

```python
# src/olav/agent.py - REMOVE FALLBACK:

# Before (lines 81-120):
olav_md_path = Path("OLAV.md")
if olav_md_path.exists():
    base_prompt = olav_md_path.read_text(encoding="utf-8")
else:
    # 🔴 DELETE THIS ENTIRE BLOCK (30+ lines)
    base_prompt = """# OLAV - Network AI Assistant
    
    You are OLAV, an AI for network operations...
    """

# After: Require OLAV.md
try:
    base_prompt = Path("OLAV.md").read_text(encoding="utf-8")
except FileNotFoundError:
    raise ValueError(
        "Required: OLAV.md not found in project root. "
        "This file is required for agent initialization."
    )
```

**Impact**: OLAV.md is now mandatory (good - enforces architecture)

---

### Phase 3: Add Explicit Caching Configuration (FEATURE)

**Objective**: Make implicit CLI caching explicit and configurable

**Add to `.olav/skills/network-cli/SKILL.md`**:

```yaml
caching:
  # Explicit caching configuration for CLI SubAgent
  enabled: true
  strategy: prompt_hash       # Cache based on normalized prompt
  ttl_seconds: 900            # 15 minutes (device state changes)
  key_fields:
    - command                 # Command executed
    - device                  # Target device
  invalidate_on_write: true   # Clear cache after config changes
  metrics:
    enabled: true             # Log cache hit/miss
    verbose: false            # Don't verbose log every hit
```

**Code Change** (optional, for enforcement):

```python
# src/olav/agents/orchestrator.py - Add cache config propagation

# When building SubAgents:
cache_config = skill.frontmatter.get("caching", {})
if cache_config.get("enabled"):
    logger.info(
        f"Caching enabled for {skill_name}: "
        f"TTL={cache_config.get('ttl_seconds')}s, "
        f"strategy={cache_config.get('strategy')}"
    )
```

**No Breaking Changes**: Caching works implicitly; this just makes it explicit.

---

### Phase 4: Add Missing SKILL Prompts

**Objective**: Ensure all skills in v0.10.2 have complete prompts

#### textfsm-generator
- Add `prompts.generation`
- Add `prompts.analysis`
- Remove hardcoded prompt builders

#### network-analysis
- Add `prompts.analysis_task` (move from analyzer.py)
- Keep existing `prompts.system`

---

## Remediation Roadmap

| Phase | Focus | Priority | Risk | Timeline |
|-------|-------|----------|------|----------|
| **P1** | Remove fallback mechanisms | 🔴 HIGH | BREAKING | Week 1 |
| **P2** | Move hardcoded prompts | 🟠 MEDIUM | Migration | Week 2 |
| **P3** | Add caching config | 🟡 LOW | None | Week 2 |
| **P4** | Cleanup + testing | 🟡 LOW | None | Week 3 |

---

## Impact Analysis

### Breaking Changes (Phase 1)

**What Breaks**:
- Deployments without SKILL.md files for all SubAgents
- Code that relies on generic fallback prompt generation
- Legacy tool discovery patterns

**Who's Affected**:
- All SubAgent deployments (must have SKILL.md)
- OLAV.md must be present (always required in v0.10+)

**Migration Path**:
1. Ensure .olav/skills/*/SKILL.md exists for all SubAgents in OLAV.md
2. Verify prompts.system in each SKILL.md
3. Verify tools list in each SKILL.md
4. Test: Run E2E tests, all SubAgents should load without fallback

### Non-Breaking (Phases 2-4)

- Code refactoring (no API changes)
- Documentation update
- Feature addition (caching config)

---

## Validation Checklist

### Phase 1 Complete Validation
- [ ] _generate_default_prompt() function deleted
- [ ] _resolve_legacy_tools() function deleted
- [ ] _load_from_skill() raises ValueError if SKILL.md missing
- [ ] All 5 SubAgents load successfully
- [ ] Error message is clear if SKILL.md missing
- [ ] agent.py base_prompt fallback deleted
- [ ] OLAV.md required at startup
- [ ] E2E tests pass

### Phase 2 Complete Validation
- [ ] textfsm_agent._build_generation_prompt() deleted
- [ ] textfsm_agent._build_analysis_prompt() deleted
- [ ] textfsm-generator SKILL.md has prompts.generation
- [ ] textfsm-generator SKILL.md has prompts.analysis
- [ ] analyzer._build_analysis_prompt() loads task from SKILL.md
- [ ] network-analysis SKILL.md has prompts.analysis_task
- [ ] Prompt behavior unchanged (same output)
- [ ] E2E tests pass

### Phase 3 Complete Validation
- [ ] network-cli SKILL.md has caching section
- [ ] Caching section documented
- [ ] Logs show cache configuration
- [ ] Cache hit/miss rates visible

### Phase 4 Complete Validation
- [ ] All unused prompt builder functions deleted
- [ ] Code coverage maintained
- [ ] Documentation updated
- [ ] E2E suite passes (all scenarios)

---

## Code Review Checklist

### Phase 1 Review
```
[ ] No fallback functions remain
[ ] All error messages are clear
[ ] No silent failures
[ ] SKILL.md always enforced
[ ] Tests verify enforcement
```

### Phase 2 Review
```
[ ] Prompts match before/after
[ ] No hardcoded templates in code
[ ] SKILL.md is source of truth
[ ] Dynamic content kept in code
[ ] Version control friendly
```

### Phase 3 Review
```
[ ] Caching config documented
[ ] No impact on performance
[ ] Metrics available
[ ] TTL appropriate
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| SKILL.md files missing | Clear error message, step-by-step recovery guide |
| Prompt behavior change | Exact text comparison before/after, sample outputs |
| Caching impacts performance | Monitor hit rates, adjust TTL based on data |
| Deployment breaks | Detailed migration guide in release notes |

---

## Files Summary

| Phase | File | Action | Lines |
|-------|------|--------|-------|
| P1 | src/olav/core/subagent_loader.py | Delete 3 functions, modify 1 | -70 lines |
| P1 | src/olav/agent.py | Delete fallback | -30 lines |
| P2 | src/olav/agents/textfsm_agent.py | Delete prompts, load from SKILL | -80 lines |
| P2 | src/olav/agents/analyzer.py | Refactor prompt building | -30 lines |
| P2 | .olav/skills/textfsm-generator/SKILL.md | Add prompts section | +40 lines |
| P2 | .olav/skills/network-analysis/SKILL.md | Add analysis_task | +20 lines |
| P3 | .olav/skills/network-cli/SKILL.md | Add caching section | +10 lines |
| P4 | docs/* | Update documentation | +50 lines |

**Total**: ~400 lines removed (code cleanup), ~120 lines added (SKILL.md configs)

---

## Next Steps

1. **Review This Document** - Confirm strategy with team
2. **Phase 1 Preparation** - Create fallback removal PR
3. **Phase 1 Implementation** - Remove fallback mechanisms
4. **Testing Phase 1** - Verify all SubAgents work
5. **Phase 2 Implementation** - Consolidate hardcoded prompts
6. **Phase 3 Implementation** - Add caching config
7. **Phase 4 Implementation** - Cleanup + docs

---

## References

📋 **Audit Documents**:
- [AUDIT_CODE_QUALITY_v0.10.1.md](AUDIT_CODE_QUALITY_v0.10.1.md) - Hardcoded prompts inventory
- [CLI_AGENT_DEEPAGENTS_ANALYSIS.md](CLI_AGENT_DEEPAGENTS_ANALYSIS.md) - Caching analysis
- [SUBAGENT_SKILL_LOADING_VERIFICATION.md](SUBAGENT_SKILL_LOADING_VERIFICATION.md) - Fallback mechanisms

📚 **Related Docs**:
- [docs/99_audit.md](docs/99_audit.md) - Previous code audit
- [docs/CLI_SKILL_REFACTORING.md](docs/CLI_SKILL_REFACTORING.md) - v0.10.1 changes

---

## Sign-Off

- **Audit Complete**: 3 major issues identified
- **Remediation Planned**: 4 phases, ~3 weeks
- **Breaking Changes**: Phase 1 (enforces architecture)
- **Code Ready**: All analysis done, implementation ready
- **Risk Level**: MEDIUM (breaking changes acceptable for architecture enforcement)

