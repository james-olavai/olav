# OLAV Skill Authoring Guide

## Overview

This guide integrates Claude's Agent Skills architecture with OLAV's specific requirements for domain-specific agents. Learn how to create effective, efficient Skills that extend OLAV's capabilities in network diagnostics, configuration management, and infrastructure analysis.

> 🔗 **Companion Guide**: For Sub-Agent **implementation** (Python code), see **[SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md)**  
> This guide focuses on **SKILL.md configuration**, while the Sub-Agent Development Guide covers **code implementation**.

**Quick Links:**
- Official docs: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Blog post: https://claude.com/blog/equipping-agents-for-the-real-world-with-agent-skills
- Support guide: https://support.claude.com/en/articles/12512198-how-to-create-custom-skills

---

## Part 1: Architecture & Design

### What is a Skill?

A Skill is an organized folder containing:
- **SKILL.md** - Main instruction file with YAML metadata and markdown body
- **Optional reference files** - Additional content (guides, references, examples)
- **Optional scripts** - Executable code that Claude can run
- **Optional resources** - Data files, configurations, examples

### Why Skills Matter for OLAV

OLAV uses Skills to:
- **Encapsulate domain expertise** - Each skill embodies knowledge for a specific network domain
- **Enable progressive disclosure** - Metadata pre-loaded, full content loaded on-demand
- **Support schema discovery** - Skills describe *how to discover* database structure vs. hardcoding it
- **Compose workflows** - Multiple skills work together to solve complex problems

### OLAV's Architectural Pattern

```
OLAV Orchestrator
├── Intent Detection (what the user wants)
├── Skill Selection (which skill(s) are needed)
├── Skill Execution (Claude + tools within the skill)
├── Result Aggregation (combine results from multiple skills)
└── Knowledge Update (store learnings for future use)
```

**Key principle:** Skills are **not** rigid procedures. They provide guidance that Claude interprets contextually. The LLM decides how to apply the skill based on:
- User intent
- Current task context
- Available tools
- Data discovered at runtime

---

## Part 2: YAML Frontmatter Requirements

### Required Fields

Every SKILL.md starts with YAML frontmatter:

```yaml
---
name: skill-name-in-kebab-case
description: Clear description of what the skill does and when to use it
---
```

### Constraints

**name field:**
- Maximum 64 characters
- Lowercase letters, numbers, hyphens only
- No XML tags or reserved words ("anthropic", "claude")
- Use gerund form (verb-ing): `analyzing-bgp`, `inspecting-interfaces`

**description field:**
- Maximum 1024 characters
- Must be non-empty
- Cannot contain XML tags
- Must include BOTH:
  - **What it does:** The capability
  - **When to use it:** Trigger conditions

### Good vs. Bad Examples

**Good description** (specific, clear triggers):
```yaml
description: Analyze BGP configuration and neighbor relationships across network devices. Use when troubleshooting routing issues, verifying BGP adjacencies, or analyzing multi-domain routing design.
```

**Bad description** (vague, no triggers):
```yaml
description: Helps with network analysis
```

### OLAV-Specific Extensions

Beyond required fields, consider adding:

```yaml
---
name: analyzing-ospf
description: [required description]
version: 1.0.0
intent: expert_diagnose  # Maps to OLAV intent system
complexity: intermediate  # simple | intermediate | expert
enabled: true           # Can be toggled in OLAV config
tools:                  # Tools this skill uses
  - query_database
  - inspect_schema
  - analyze_topology
requirements:           # External dependencies
  - python >= 3.8
  - duckdb >= 0.8.0
examples:               # Example queries
  - "Analyze OSPF convergence time across the network"
  - "Find OSPF areas with suboptimal design"
---
```

---

## Part 3: Skill Structure & Progressive Disclosure

### The Three Levels of Detail

Claude loads your Skill in stages:

**Level 1: Metadata (Always loaded)**
- name and description from YAML frontmatter
- Pre-loaded at startup for all skills
- Claude uses this to decide IF the skill is relevant

**Level 2: Main content (Loaded if skill is triggered)**
- SKILL.md body content
- Loaded only after Claude decides the skill applies
- Should contain essential navigation and quick-start guidance

**Level 3: Reference files (Loaded as needed)**
- Additional .md files referenced from SKILL.md
- Loaded only when Claude needs specific details
- Examples: advanced features, API references, detailed workflows

### Simple Skill Structure

For straightforward skills, just SKILL.md:

```
network-inspection/
└── SKILL.md
    ├── [YAML frontmatter]
    ├── Quick start
    ├── Common workflows
    └── Advanced features reference
```

### Medium Complexity Structure

When SKILL.md approaches 300+ lines, split content:

```
bgp-analysis/
├── SKILL.md (overview + quick start)
├── CONFIGURATION.md (BGP configuration patterns)
├── TROUBLESHOOTING.md (common BGP issues)
├── REFERENCE.md (BGP commands + outputs)
└── examples/
    ├── example1.txt
    └── example2.txt
```

Map in SKILL.md:

```markdown
## BGP Analysis Workflows

**Configuration audit**: See [CONFIGURATION.md](CONFIGURATION.md)
**Troubleshooting**:
  - Convergence issues → [TROUBLESHOOTING.md#convergence](TROUBLESHOOTING.md#convergence)
  - Loop prevention → [TROUBLESHOOTING.md#loops](TROUBLESHOOTING.md#loops)
**API reference**: See [REFERENCE.md](REFERENCE.md)
```

### Complex Multi-Domain Structure

When managing multiple domains (finance, sales, product):

```
bigquery-analysis/
├── SKILL.md (navigation hub)
└── reference/
    ├── devices.md (network device metrics)
    ├── interfaces.md (interface health)
    ├── routing.md (routing protocol analysis)
    └── protocols.md (OSPF, BGP, EIGRP)
```

---

## Part 4: Writing Effective SKILL.md Body

### Conciseness Principle

**Context window is a shared resource.** Every token in your skill competes with:
- System prompt
- Conversation history
- Other skills' metadata
- The user's actual request

**Rule of thumb:** Keep SKILL.md body under 400 lines for optimal performance.

### Challenge Every Piece of Content

Before including information, ask:
- Does Claude really need this explanation?
- Can I assume Claude already knows this?
- Does this paragraph justify its token cost?

**Over-explanation example (BAD - ~150 tokens):**
```markdown
## Extract PDF Text

PDF (Portable Document Format) files are a common file format that contains 
text, images, and other content. To extract text from a PDF, you'll need to 
use a library. There are many libraries available...
```

**Concise version (GOOD - ~50 tokens):**
```markdown
## Extract PDF Text

Use pdfplumber for text extraction:
```python
import pdfplumber

with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```
```

The concise version assumes Claude knows what PDFs are and how libraries work.

### Structure: Navigation First

Start with a table of contents:

```markdown
# [Skill Name]

## Quick Start
[3-5 lines on what this skill does and its primary use case]

## Workflows
1. [Workflow 1]: See [WORKFLOW1.md](WORKFLOW1.md)
2. [Workflow 2]: See [WORKFLOW2.md](WORKFLOW2.md)
3. [Workflow 3]: Description + inline examples

## Tools
- Tool 1: Brief description
- Tool 2: Brief description

## Advanced Features
[Link to separate files for advanced topics]
```

### Core Principles for OLAV Skills

#### 1. Schema-Aware, Not Schema-Hardcoded

**BAD (hardcoded schema):**
```markdown
## Available Tables
- devices: hostname, ip_address, vendor, model, ios_version
- raw_outputs: device, command, output, sync_date
```

**GOOD (schema discovery):**
```markdown
## Schema Discovery

1. Start with `inspect_schema()` to list available tables
2. Use `inspect_schema('table_name')` for column details
3. Build queries based on discovered structure
4. Don't assume specific tables exist - always verify first
```

**Why:** The database schema evolves. Hardcoding creates brittle skills that break when schema changes. Let Claude discover at runtime.

#### 2. Set Appropriate Degrees of Freedom

Match flexibility to task complexity:

**High freedom (general guidance):**
Use when multiple approaches are valid:
```markdown
## Code Review Strategy

1. Analyze code structure and organization
2. Check for potential bugs or edge cases
3. Suggest improvements for readability
4. Verify adherence to project conventions
```

**Medium freedom (parameterized):**
Use when a pattern exists but variations are OK:
```markdown
## Generate Progress Report

Use this structure, customize sections as needed:
- Executive summary
- Key metrics
- Risks & blockers
- Next steps
```

**Low freedom (specific procedure):**
Use for fragile/deterministic operations:
```markdown
## Database Migration

Run exactly this command:
`python scripts/migrate.py --verify --backup`

Do not modify flags or add additional arguments.
```

#### 3. Avoid Hardcoded Configuration

**BAD:**
```python
CRITICAL_THRESHOLD = 80  # CPU usage threshold
```

**GOOD:**
```python
# CPU utilization considered critical at 80%
# This threshold balances alert fatigue vs. coverage
CRITICAL_THRESHOLD = 80
```

Justify all parameters. If you don't know why a value is chosen, Claude won't either.

---

## Part 5: Tools & Code in Skills

### When to Use Scripts vs. Instructions

**Use scripts when:**
- Operation is deterministic (sorting, parsing, transformation)
- Reliability is critical (validation, security)
- Complex logic improves efficiency
- Output format must be exact

**Use markdown instructions when:**
- Multiple approaches are valid
- Context determines the best path
- Task requires reasoning/analysis
- Output flexibility is needed

### Script Best Practices

#### 1. Handle Errors Explicitly

**BAD (punt to Claude):**
```python
def process_file(path):
    return open(path).read()  # Will fail if file missing
```

**GOOD (handle gracefully):**
```python
def process_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        print(f"File {path} not found, creating with defaults")
        with open(path, 'w') as f:
            f.write('{}')  # Default structure
        return '{}'
    except PermissionError:
        print(f"Cannot access {path}, using backup location")
        return load_backup()
```

#### 2. Self-Document Constants

**BAD (magic numbers):**
```python
REQUEST_TIMEOUT = 47
RETRIES = 5
```

**GOOD (explained):**
```python
# HTTP requests typically complete within 30 seconds
# Longer timeout accounts for slow/unreliable connections
REQUEST_TIMEOUT = 30

# Three retries balances reliability vs. speed
# Most intermittent failures resolve by second retry
MAX_RETRIES = 3
```

#### 3. Validate Before Executing

For complex operations, use the plan-validate-execute pattern:

```markdown
## Form Filling Workflow

1. **Analyze** form: `python scripts/analyze_form.py input.pdf`
2. **Create** mapping: Edit `fields.json` with values
3. **Validate** mapping: `python scripts/validate.py fields.json`
4. **Apply** changes: `python scripts/fill_form.py input.pdf fields.json`
5. **Verify** output: Check result before proceeding
```

This catches errors early without touching original data.

### Referencing External Tools

If your skill uses MCP (Model Context Protocol) tools, use fully qualified names:

```markdown
Use the BigQuery:query_table tool to retrieve data
Use the GitHub:create_issue tool to create issues
```

Format: `ServerName:tool_name`

---

## Part 6: Workflows & Feedback Loops

### Multi-Step Workflow Pattern

For complex tasks, provide checklis

s Claude can track:

```markdown
## Data Validation Workflow

Copy and check off as you go:

- [ ] Step 1: Load data file
- [ ] Step 2: Validate schema
- [ ] Step 3: Check for nulls
- [ ] Step 4: Verify constraints
- [ ] Step 5: Preview sample

**Step 1: Load data file**
...

**Step 2: Validate schema**
...
```

### Feedback Loop Pattern

Build validation into workflows:

```markdown
## Content Review Process

1. Draft content following STYLE_GUIDE.md
2. Check terminology against GLOSSARY.md
3. Verify examples match EXAMPLE_PATTERNS.md
4. If issues found:
   - Note specific problems
   - Revise the content
   - Repeat steps 2-3 until no issues
5. Only proceed when all checks pass
```

The "validator" can be:
- A reference document file
- An executable script
- A checklist of rules

---

## Part 7: OLAV-Specific Patterns

> 💡 **Implementation Details**: For Python code implementation of these patterns, see **[SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md)**

### 1. Intent Mapping

OLAV skills should declare their intent type:

```yaml
---
name: network-oss-path-analysis
description: Trace OSP path between two network nodes, identify convergence delays and suboptimal paths
intent: expert_diagnose  # Orchestrator routes to Expert agent
complexity: expert
---
```

Intent values map to OLAV's agent roles:
- `quick_query` → Query Agent (fast, database-focused)
- `analysis` → Analysis Agent (pattern recognition, diagnostics)
- `expert_diagnose` → Expert Agent (complex, multi-layer investigation)
- `inspection` → Inspection Agent (health checks, compliance)

### 2. Database Access Pattern

OLAV skills should NOT hardcode database details:

```markdown
## Query Database

Use `query_database()` tool with discovered schema:

1. First: `inspect_schema()`  → List available tables
2. Then: `inspect_schema('table_name')`  → See columns
3. Build: SQL query based on what you discovered
4. Execute: `query_database(sql)`

The database path is managed centrally - don't construct paths yourself.
```

### 3. Knowledge Base Integration

OLAV skills can contribute to and learn from the knowledge base:

```markdown
## Learning from Experience

If this workflow reveals new patterns:
1. Document findings in a new knowledge base entry
2. Include: symptom, root cause, solution, validation
3. Commit to .olav/knowledge/
4. Next similar queries will find this case

Shared knowledge makes OLAV continuously smarter.
```

### 4. Configuration via Frontmatter

Use SKILL.md frontmatter for operational control:

```yaml
---
name: bgp-convergence-analysis
enabled: true              # Can disable skill
version: 2.1.0            # Track skill versions
retry_limit: 3             # Orchestrator respects this
timeout_seconds: 120       # Max execution time
cache_ttl_seconds: 3600    # How long to cache results
---
```

---

## Part 8: Testing & Iteration

### Evaluation-Driven Development

Build evaluations BEFORE extensive documentation:

1. **Identify gaps**: Run Claude on representative tasks without the skill. Note specific failures.
2. **Create evaluations**: Build 3-5 scenarios testing each gap.
3. **Establish baseline**: Measure Claude's performance without the skill.
4. **Write minimal instructions**: Just enough to address the gaps and pass evaluations.
5. **Iterate**: Execute evaluations, compare, refine.

### Evaluation Structure

```json
{
  "skills": ["analyzing-bgp"],
  "query": "Find BGP route flapping on R1 in the last 6 hours",
  "files": ["network_logs/route_changes.txt"],
  "expected_behavior": [
    "Queries relevant database tables",
    "Analyzes BGP update history",
    "Identifies the flapping routes with change frequency",
    "Suggests root cause (interface instability, configuration, etc.)",
    "Recommends specific diagnostic commands"
  ]
}
```

### Test with Multiple Models

Skills behave differently across models:

- **Claude Haiku**: Fast, economical. Does the skill provide enough guidance?
- **Claude Sonnet**: Balanced. Is the skill clear and efficient?
- **Claude Opus**: Powerful reasoning. Is the skill avoiding over-explanation?

Test with all models you plan to support.

### Iterative Improvement with Claude

The most effective process:

1. **Complete task with Claude**: Use normal prompting. Notice what context you repeatedly provide.
2. **Identify reusable patterns**: Extract the procedural knowledge that would help future similar tasks.
3. **Ask Claude to create the skill**: "Create a Skill capturing this pattern. Include the schemas, naming conventions, and filtering rules."
4. **Review for conciseness**: Claude may over-explain. Ask: "Remove the explanation about X - Claude already knows that."
5. **Test on fresh instance**: Give the skill to a fresh Claude instance on related tasks.
6. **Observe behavior**: Where does Claude struggle? What does it ignore?
7. **Iterate**: Return to Claude with observations. "When using this skill, Claude forgot to filter by date. Should we reorganize?"

---

## Part 9: Common Patterns

### Template Pattern

For strict format requirements:

```markdown
## Report Structure

ALWAYS use this exact template:

# [Title]

## Executive Summary
[One paragraph overview]

## Key Findings
- Finding 1 with data
- Finding 2 with data

## Recommendations
1. Actionable recommendation
2. Actionable recommendation
```

For flexible guidance:

```markdown
## Report Structure (Suggested Format)

Adapt based on analysis type:

# [Title]

## Executive Summary
[Overview - can be 1-3 paragraphs]

## Key Findings
[Organize sections based on what you discover]

## Recommendations
[Tailor to specific context]
```

### Examples Pattern

Show input/output pairs:

```markdown
## Commit Message Format

**Example 1:**
User: "Added JWT authentication"
Output:
```
feat(auth): implement JWT-based authentication

Add login endpoint and token validation middleware
```

**Example 2:**
User: "Fixed date bug in reports"
Output:
```
fix(reports): correct date formatting in timezone conversion

Use UTC timestamps consistently across report generation
```
```

### Conditional Workflow Pattern

Guide through decision points:

```markdown
## Modification Workflow

1. What are you doing?

   **Creating new content?** → See "Creation Workflow" below
   **Editing existing?** → See "Editing Workflow" below

2. Creation Workflow:
   - Use appropriate tool
   - Build from scratch
   - Export result

3. Editing Workflow:
   - Load existing content
   - Apply modifications
   - Validate changes
   - Save result
```

---

## Part 10: Checklist for Effective Skills

### Core Quality
- ✅ Description specifies what AND when to use
- ✅ SKILL.md body under 400 lines (or split into reference files)
- ✅ No time-sensitive information
- ✅ Consistent terminology throughout
- ✅ Examples are concrete, not abstract
- ✅ File references are one level deep (avoid nested references)
- ✅ Progressive disclosure used appropriately

### OLAV-Specific
- ✅ Intent type declared in frontmatter
- ✅ No hardcoded database schema
- ✅ Uses `inspect_schema()` for runtime discovery
- ✅ No hardcoded configuration paths
- ✅ All paths use forward slashes
- ✅ Tool usage clearly marked (execute vs. read)

### Code & Scripts
- ✅ Scripts solve problems, don't punt to Claude
- ✅ Error handling is explicit
- ✅ All constants are justified
- ✅ Dependencies listed and verified available
- ✅ Validation steps for critical operations
- ✅ Feedback loops for quality tasks

### Testing
- ✅ At least 3 evaluations created
- ✅ Tested with Haiku, Sonnet, and Opus
- ✅ Tested with real usage scenarios
- ✅ Team feedback incorporated

---

## Part 11: Anti-Patterns to Avoid

### ❌ Hardcoded Assumptions
```markdown
# BAD: Assumes specific schema
SELECT device, command, output FROM raw_outputs
```

```markdown
# GOOD: Discovers schema at runtime
Call inspect_schema() first, then build queries
```

### ❌ Too Many Options
```markdown
# BAD
You can use pypdf, pdfplumber, PyMuPDF, pdf2image, or...
```

```markdown
# GOOD
Use pdfplumber for text extraction. For scanned PDFs 
requiring OCR, use pdf2image with pytesseract instead.
```

### ❌ Over-Explanation
```markdown
# BAD - 200+ tokens
PDF files are a common format. To work with them, you need 
a library. There are many available. We recommend pdfplumber 
because...
```

```markdown
# GOOD - 50 tokens
Use pdfplumber for PDF processing:
```python
import pdfplumber
```

### ❌ Windows-Style Paths
```markdown
# BAD
scripts\helper.py
reference\GUIDE.md
```

```markdown
# GOOD
scripts/helper.py
reference/GUIDE.md
```

### ❌ Nested File References
```markdown
# BAD: Deep nesting
SKILL.md → advanced.md → details.md → actual_content.md
```

```markdown
# GOOD: One level deep
SKILL.md → [advanced.md, reference.md, examples.md]
All reference files link directly from SKILL.md
```

---

## Part 12: Examples from OLAV Skills

### Network Inspection Skill

```yaml
---
name: network-inspection
description: Multi-layer network health inspection (L1-L4). Use for health checks, anomaly detection, compliance validation, or SLA monitoring.
version: 2.1.0
intent: inspection
complexity: intermediate
enabled: true
tools:
  - inspect_schema
  - query_database
  - discover_data
---

# Network Health Inspection

## Quick Start

Network health inspection covers L1-L4 layers. Use this skill when:
- Detecting anomalies or compliance violations
- Performing SLA health checks
- Troubleshooting multi-layer issues
- Validating network baseline

## Inspection Layers

**Layer 1 (Physical):** Device health, version, uptime
**Layer 2 (Data Link):** Interfaces, neighbors, spanning tree
**Layer 3 (Network):** Routing protocols, topology, IP reachability
**Layer 4 (Application):** CPU, memory, performance metrics

## Schema-Aware Approach

1. Start: `inspect_schema()` → discover available tables/views
2. Analyze: `inspect_schema('table_name')` → understand structure
3. Query: `query_database(sql)` → analyze specific layers
4. Report: Aggregate findings by layer

## Advanced Features

See [LAYER_PATTERNS.md](LAYER_PATTERNS.md) for L1-L4 query patterns
See [THRESHOLDS.md](THRESHOLDS.md) for configurable health thresholds
```

### Network Query Skill

```yaml
---
name: network-query
description: Query network state from DuckDB database using SQL. Returns device inventory, interface information, routing tables, and parsed CLI outputs. Use for data retrieval, reporting, and CSV exports.
version: 1.5.0
intent: quick_query
enabled: true
tools:
  - query_database
  - inspect_schema
  - discover_data
---

# Network Query

## Schema Discovery (Important!)

**Never hardcode table or column names.** Always:

1. Call `inspect_schema()` to list available tables
2. Call `inspect_schema('table')` to see columns
3. Build queries based on discovered schema
4. Never assume tables exist - verify first

## Query Tools

- `query_database(sql)`: Execute SQL on unified DuckDB database
- `inspect_schema()`: List all tables and views
- `inspect_schema('name')`: See structure of specific table
- `discover_data()`: Find exported files in exports/

## Common Query Patterns (After Schema Discovery)

Once you've inspected schema, common patterns include:
- Device metadata queries
- CLI output retrieval  
- Cross-device aggregation
- Time-series analysis

See [QUERY_PATTERNS.md](QUERY_PATTERNS.md) for examples
```

---

## Part 13: Additional Resources

### Official Documentation
- **Best Practices**: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- **Quick Start**: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/quickstart
- **OLAV Internal Documentation
- ⭐ **Sub-Agent Development Guide**: [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md) - **How to implement Sub-Agents in Python**
- **Architecture Guide**: [architecture_correct_understanding.md](architecture_correct_understanding.md)
- **Audit Report**: [99_audit.md](99_audit.md)

### API Guide**: https://platform.claude.com/docs/en/build-with-claude/skills-guide

### Tutorials & Examples
- **Blog Post**: https://claude.com/blog/equipping-agents-for-the-real-world-with-agent-skills
- **GitHub Examples**: https://github.com/anthropics/skills
- **How to Create Skills**: https://support.claude.com/en/articles/12512198-how-to-create-custom-skills

### Frameworks
- **Agent Skills Standard**: https://agentskills.io/ (open standard for cross-platform skills)
- **Model Context Protocol**: https://modelcontextprotocol.io/ (complement to Skills)

---

## Summary: Your Skill Development Workflow

1. **Evaluate First**: Run tasks without a skill. Identify specific gaps.
2. **Create Minimal SKILL.md**: Write just enough to pass your evaluations.
3. **Structure for Progressive Disclosure**: Use separate files for advanced content.
4. **Test with Claude**: Ask Claude to help refine the skill.
5. **Observe Real Usage**: How does Claude actually use it? Iterate based on observations.

---

## Next Steps

- **Implement Sub-Agent Code**: See [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md) for Python implementation patterns
- **Review Examples**: Study existing skills in `.olav/skills/`
- **Test Your Skill**: Create evaluations and iterate based on results
6. **Document for OLAV**: Include intent type, use schema discovery, no hardcoding.
7. **Test Across Models**: Ensure Haiku, Sonnet, and Opus all work well.
8. **Iterate**: Better skills come from repeated testing and refinement.

Your skills extend Claude's capabilities. Well-crafted skills make OLAV smarter, faster, and more reliable.

