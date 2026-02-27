# Plan: Add Document Expert Skill for Change Plan Generation

## Goal
Implement a document expert skill that can generate structured change plans, HLD, and LLD documents in markdown format.

## Steps

### 1. Create document templates skill directory structure
- [x] Create `.olav/skills/ops-DocTemplates/templates/`

### 2. Define change_plan.md template
- [ ] Create `change_plan.md` with complete change plan template
- Fields: Executive Summary, Scope, Current State, Target State, Change Details, Rollback Plan, Verification, Communication, Risk, Approvals

### 3. Define hld.md template  
- [ ] Create `hld.md` with High Level Design template
- Fields: Overview, Architecture, Requirements, Design Decisions, Dependencies, Timeline

### 4. Define lld.md template
- [ ] Create `lld.md` with Low Level Design template
- Fields: Technical Specifications, Interface Definitions, Data Models, Configuration Details, Implementation Steps

### 5. Create SKILL.md for doc-templates
- [ ] Create `.olav/skills/ops-DocTemplates/SKILL.md`
- Define as agent type, category network-documentation
- Tools: format_and_export (reused from quick-Query)

### 6. Create system prompt for document expert
- [ ] Create `.olav/skills/ops-DocTemplates/prompts/system.md`
- Role: "You are a network documentation expert"
- Instructions: Load templates from templates/ directory and fill them based on user request

### 7. Register new skill in OLAV.md
- [ ] Add ops-DocTemplates to ops agent skills list in `.olav/OLAV.md`

### 8. Test with user query and fix issues
- [ ] Run: `echo "I want to migrate my cisco ios R1 and R2 to juniper junos system, give change plan including all configuration, save the plan as markdown format" uv run olav -a ops`
- [ ] Verify output contains structured change plan
- [ ] Fix any issues encountered

## Notes
- Reuse existing `format_and_export` tool from quick-Query skill
- Templates should be filled by LLM based on user input
- No hardcoded formats - use templates as reference
