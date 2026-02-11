# System Admin Agent - Reference Documentation Index

This directory contains essential OLAV documentation to help you understand and customize OLAV.

## 📚 Available References

### Core Architecture
- **[ARCHITECTURE.md](ARCHITECTURE.md)** (17KB)
  - How OLAV is structured
  - Component hierarchy and data flow
  - Agent orchestration patterns
  - Caching and persistence mechanisms
  - **Use when**: Understanding OLAV structure, designing new components

### Development Guides

- **[QUICK_START_DEVELOPER.md](QUICK_START_DEVELOPER.md)** (15KB)
  - 5-minute onboarding for new developers
  - Setup instructions
  - Running first query
  - Common workflows
  - **Use when**: Getting started with OLAV development

- **[SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md)** (39KB) ⭐ **Recommended**
  - How to create new agents
  - ReAct pattern implementation
  - State management
  - Tool registration
  - Testing approached
  - **Use when**: Building custom agents from scratch

- **[SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md)** (26KB) ⭐ **Recommended**
  - How to write SKILL.md files
  - Agent configuration structure
  - Prompt engineering
  - Tool registration and permissions
  - Examples and templates
  - **Use when**: Creating or modifying agent skills

- **[TOOL_DEVELOPMENT_GUIDE.md](TOOL_DEVELOPMENT_GUIDE.md)** (20KB)
  - How to create new tools (@tool decorator)
  - Tool interface standards
  - Input/output patterns
  - Error handling
  - Integration with agents
  - **Use when**: Extending existing tools or creating new ones

### Configuration & Database

- **[CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md)** (18KB)
  - Complete configuration file reference
  - .env variables
  - settings.json structure
  - SKILL.md frontmatter format
  - Configuration priority chain
  - **Use when**: Adjusting OLAV settings or creating new config sections

- **[DATABASE_GUIDE.md](DATABASE_GUIDE.md)** (18KB)
  - DuckDB schema and structure
  - Available tables and views
  - Query patterns
  - Performance tuning
  - **Use when**: Working with data storage or optimization

### Quality & Contribution

- **[TESTING_QUICK_REFERENCE.md](TESTING_QUICK_REFERENCE.md)** (9KB)
  - Test standards (E2E testing)
  - How to write real tests
  - Mock-free testing patterns
  - Running tests
  - **Use when**: Writing or modifying tests

- **[CONTRIBUTING.md](CONTRIBUTING.md)** (14KB)
  - Development standards
  - Code quality expectations
  - Git workflow
  - PR guidelines
  - **Use when**: Contributing changes or understanding expectations

---

## 🎯 Quick Usage Guide

### "I want to create a custom agent"
→ Read in order:
1. QUICK_START_DEVELOPER.md (setup context)
2. SUB_AGENT_DEVELOPMENT_GUIDE.md (agent creation)
3. SKILL_AUTHORING_GUIDE.md (configuration)

### "I want to add a new tool"
→ Read:
1. TOOL_DEVELOPMENT_GUIDE.md
2. SKILL_AUTHORING_GUIDE.md (registration section)

### "I want to understand OLAV architecture"
→ Read:
1. ARCHITECTURE.md (overview)
2. CONFIGURATION_REFERENCE.md (config structure)
3. DATABASE_GUIDE.md (data layer)

### "I want to modify an existing agent"
→ Read:
1. ARCHITECTURE.md (understand component hierarchy)
2. SKILL_AUTHORING_GUIDE.md (understand current SKILL.md)
3. Relevant code via search_code() tool

### "I'm debugging a performance issue"
→ Read:
1. ARCHITECTURE.md (caching section)
2. DATABASE_GUIDE.md (optimization section)
3. TESTING_QUICK_REFERENCE.md (profiling)

### "I want to extend a tool"
→ Read:
1. TOOL_DEVELOPMENT_GUIDE.md
2. Search existing tool code with search_code()

---

## 🔍 How to Use These References

This documentation is designed to be read by the System Admin Agent. When you ask about:
- **How to create something** → Agent will read the relevant guide and explain
- **How something works** → Agent will check ARCHITECTURE.md and explain the design
- **How to configure something** → Agent will reference CONFIGURATION_REFERENCE.md
- **How to test something** → Agent will guide you through TESTING_QUICK_REFERENCE.md

### Example Queries

**Example 1: Create custom agent**
```
User: "Create a new agent that checks server status"
Agent: 
1. Reads SUB_AGENT_DEVELOPMENT_GUIDE.md
2. Shows you the structure needed
3. Creates the agent code
4. Creates SKILL.md based on SKILL_AUTHORING_GUIDE.md
```

**Example 2: Extend a tool**
```
User: "I want the query-engine to also export to XML"
Agent:
1. Searches code for existing export tools
2. Reads TOOL_DEVELOPMENT_GUIDE.md
3. Shows you how to extend the tool
4. Implements and tests the change
```

**Example 3: Understand the architecture**
```
User: "How does the query orchestration work?"
Agent:
1. Reads ARCHITECTURE.md (orchestration section)
2. Searches code for orchestrator implementation
3. Explains the flow with examples
```

---

## 📝 Document Statistics

| Document | Size | Topics | Best For |
|----------|------|--------|----------|
| ARCHITECTURE.md | 17KB | Structure, flow, caching | Understanding design |
| CONFIGURATION_REFERENCE.md | 18KB | Config files, env vars | Setup & customization |
| CONTRIBUTING.md | 14KB | Standards, workflow | Contributing code |
| DATABASE_GUIDE.md | 18KB | Queries, optimization | Data management |
| QUICK_START_DEVELOPER.md | 15KB | Setup, first steps | Getting started |
| SKILL_AUTHORING_GUIDE.md | 26KB | SKILL.md format, prompts | Creating agents |
| SUB_AGENT_DEVELOPMENT_GUIDE.md | 39KB | Agent creation, ReAct | Building agents |
| TESTING_QUICK_REFERENCE.md | 9KB | E2E tests, standards | Quality assurance |
| TOOL_DEVELOPMENT_GUIDE.md | 20KB | @tool decorator, patterns | Creating tools |
| **Total** | **176KB** | 50+ topics | Complete guide |

---

## 🚀 Recommended Reading Order

**For new developers:**
1. QUICK_START_DEVELOPER.md
2. ARCHITECTURE.md
3. CONFIGURATION_REFERENCE.md

**For agent creation:**
1. SUB_AGENT_DEVELOPMENT_GUIDE.md
2. SKILL_AUTHORING_GUIDE.md
3. TOOL_DEVELOPMENT_GUIDE.md

**For everyday customization:**
1. SKILL_AUTHORING_GUIDE.md
2. TOOL_DEVELOPMENT_GUIDE.md
3. CONFIGURATION_REFERENCE.md

**For advanced work:**
1. ARCHITECTURE.md (full)
2. DATABASE_GUIDE.md
3. CONTRIBUTING.md

---

**Last Updated**: 2026-02-08
**Total Documentation**: 176 KB, 6509 lines
**Status**: ✅ Available for Agent and User reference
