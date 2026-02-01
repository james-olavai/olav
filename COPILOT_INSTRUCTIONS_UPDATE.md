# Copilot Instructions Update - v0.9.8

## Summary
Updated `.github/copilot-instructions.md` to enforce Skill-Centric Architecture and No Hardcoded Configuration principles from Phase 1-2 improvements.

## Changes Made

### 1. Added Skill-Centric Architecture Section
- Definition: All configuration flows from SKILL.md files
- Location: `.olav/skills/*/SKILL.md`
- Authority: SKILL.md frontmatter is single source of truth
- Fallback: settings.py provides application-level defaults

### 2. Added No Hardcoded Configuration Guidelines
**Rule**: Zero hardcoded parameters (paths, thresholds, weights, commands)
**Requirements**:
- Use `config.paths.*` for all file paths
- Use `config.settings.*` for all parameters
- Support environment variable overrides via `.env`
- Support user overrides via `.olav/settings.json`
- Support task-specific overrides via SKILL.md frontmatter

### 3. Added Configuration Priority Chain
```
Priority (highest to lowest):
1. .env file
2. .olav/settings.json (user configuration)
3. SKILL.md frontmatter (task-specific)
4. config/settings.py (application defaults)
5. Code hardcoded values (fallback only)
```

### 4. Added Configuration File Locations Reference
**From `config/paths.py`**:
- ROUTING_RULES_PATH → .olav/config/routing_rules.yaml
- SKILL_BASE_PATH → .olav/skills/
- CONFIG_DIR → .olav/config/
- REPORTS_DIR → exports/reports/
- SNAPSHOTS_DIR → exports/snapshots/
- CACHE_DB_PATH → .olav/cache/semantic_cache.db

**Environment Variable Overrides**:
- NORNIR_GROUP → Nornir device group
- CRITICAL_WEIGHT → Health score critical weight
- WARNING_WEIGHT → Health score warning weight
- HEALTH_THRESHOLD_HEALTHY → Health score threshold (%)

## File Location
- **File**: `.github/copilot-instructions.md`
- **Status**: Not tracked by git (in .gitignore), but provides reference for development
- **Access**: Available in workspace for all developers and AI agents

## Related Documentation
- [Phase 1-2 Completion Summary](PHASE1_PHASE2_COMPLETION_SUMMARY.md)
- [Hardcode Fixes Summary](HARDCODE_FIXES_SUMMARY.md)
- [Development Guide](docs/00_development_guide.md)

## Impact
All new agents and skills should:
1. ✅ Store configuration in SKILL.md frontmatter
2. ✅ Read paths from `config.paths`
3. ✅ Read parameters from `config.settings`
4. ✅ Support environment variable overrides
5. ✅ Never hardcode paths, parameters, or vendor-specific values

---

**Updated**: 2026-02-01  
**Version**: v0.9.8
