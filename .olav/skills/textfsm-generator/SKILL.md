---
name: generating-textfsm-parsers
description: Automatically generate and optimize TextFSM templates for cross-vendor CLI command parsing. Use when creating new parsers, improving extraction accuracy, learning field mappings, or normalizing data formats.
version: 2.0.0
intent: self-learning
tools:
  - query_database
  - discover_data
prompts:
  system: |
    You are a TextFSM template expert for network command output parsing. Your goal is to generate high-quality TextFSM templates that accurately parse vendor-specific CLI outputs and learn field name mappings.

    **IMPORTANT**: You have access to the NTC Template Library with 939+ verified templates at:
    `.venv/lib/python3.12/site-packages/ntc_templates/templates/`
    
    BEFORE generating a template, ALWAYS:
    1. Check if a similar template exists in NTC (e.g., cisco_ios_show_bgp_summary.textfsm)
    2. Study its structure as a reference for correct syntax
    3. Apply the same design patterns (Value definitions → State machine → Record transitions)
    4. Use NTC examples to validate your generated template structure

    **Key Responsibilities**:
    1. Analyze raw command output structure and patterns
    2. Generate syntactically valid TextFSM templates (using NTC as reference)
    3. Achieve >80% extraction rate on sample data
    4. Pass Pydantic validation for all extracted fields
    5. Learn and map cross-vendor field names to standardized models

    **Critical TextFSM Syntax Rules** (from NTC best practices):
    - **Values first**: All Value/List/Filldown declarations MUST come before "Start"
    - State names: Must match pattern ^[A-Za-z_][A-Za-z0-9_]*$
    - No special characters or spaces in state names
    - Each state must have >= 1 transition (-> State, -> Record, or -> END)
    - Values: Use `Value` for single fields, `List` for repeated items, `Filldown` for persistent
    - Pattern anchors: ^ (line start), $ (line end) - use them to match exactly
    - State transitions: Format is `-> StateName` or `-> Record` (NOT `->`something else)
    - Common states: `Start` (entry), `Record` (output results), `END` (exit)
  
  generation: |
    Generate a TextFSM template to parse the following command output.
    
    REFERENCE: Study the NTC template structure below for correct syntax patterns.
    
    **Template Structure** (from NTC best practices):
    ```textfsm
    Value FieldName (regex_pattern)
    Value List ListField (\d+\.\d+\.\d+\.\d+)
    Value Filldown Persistent (\S+)
    
    Start
      ^pattern matches line with ${FieldName} -> StateA
      ^other pattern -> Record
    
    StateA
      ^nested line ${ListField} -> Record
      ^return to start -> Start
    ```
    
    **Critical Requirements**:
    1. Return ONLY the template (no markdown, no explanations, no code blocks)
    2. **Values MUST come before Start** - all Value/List/Filldown declarations first
    3. Validate all state names match pattern ^[A-Za-z_][A-Za-z0-9_]*$
    4. Ensure every state has >= 1 valid transition (-> StateName or -> Record)
    5. Make regex patterns match the actual output format exactly
    6. Use Filldown ONLY for values that persist across multiple records
    7. Use List for fields that appear multiple times
    8. Patterns must use ^ and $ anchors where they match output
    9. Test against all sample data to achieve >80% extraction

    Return format: Plain TextFSM template (no backticks, no explanation).
    Example output format (copy this structure):
    ```
    Value VRF (\S+)
    Value BGP_Router_ID (\S+)
    
    Start
      ^BGP\s+router\s+ID\s+${BGP_Router_ID} -> Record
    ```
  
  analysis: |
    Analyze the TextFSM template failure and provide specific fixes.
    
    Diagnosis Process (detailed):
    1. **Syntax Errors** - Identify exact issues:
       - Invalid state names (must match ^[A-Za-z_][A-Za-z0-9_]*$)
       - Missing transitions (every state needs -> or record action)
       - Value definitions in wrong place (must be BEFORE Start)
       - Invalid state references (-> to undefined states)
    
    2. **Pattern Validation** - Check regex patterns:
       - Do patterns actually match the sample output?
       - Are anchors (^ and $) used correctly?
       - Are capture groups correct (${FieldName})?
    
    3. **State Machine Logic**:
       - Verify state transitions are logical
       - Check Record transitions place in correct states
       - Ensure no infinite loops
    
    4. **Extraction Quality**:
       - Count records extracted vs. expected (extraction rate)
       - List which records failed to extract
       - Identify missing fields from successful records
    
    5. **Pydantic Validation**:
       - Check field type mismatches
       - Verify required fields are present
    
    6. **Compare Against NTC Templates**:
       - If similar NTC template exists, compare structure
       - Use NTC template patterns as reference for fixes
    
    Provide concise analysis with specific fixes for EACH issue found.
    Format fixes as exact template corrections (line by line if needed).
intent_matching:
  - "Generate TextFSM template"
  - "Create parser for"
  - "Learn field mapping"
  
constraints:
  max_iterations: 10              # ReAct loops with feedback
  min_extraction_rate: 0.80       # 80% record extraction minimum
  min_confidence: 0.80            # LLM confidence for field mappings
  require_human_review: true      # User approval before saving
  pydantic_validation: true       # Must pass Pydantic validation
  cache_mappings: true            # Persist learned mappings

output:
  templates:
    format: textfsm
    location: .olav/config/textfsm/
    metadata: true                # Generate .meta file with quality metrics
  mappings:
    format: json
    location: .olav/config/mappings/
---

# TextFSM Template Generator & Field Mapping Learner

## Overview

This skill provides two complementary self-learning capabilities:
1. **TextFSM Template Generator** - Automatically generate parsing templates for vendor CLI outputs
2. **Field Mapping Learner** - Discovers and learns cross-vendor field name mappings

## Architecture

Unified data normalization pipeline for cross-vendor command parsing:

```
Raw CLI Output (vendor-specific)
    ↓
[TextFSM Template Generator]
    ├─ Template exists? → Use it
    ├─ Missing? → Generate new
    └─ Poor quality? → Regenerate
    ↓
Parsed Data (vendor fields)
    ↓
[Field Mapping Learner]
    ├─ Mapping exists? → Use it  
    └─ Missing? → Learn new mapping
    ↓
Normalized Data (standardized models)
```

**Data Flow Example**:
- Cisco: `{"BGP_NEIGHBOR": "10.0.0.1", "NEIGHBOR_AS": 65001}`
- Juniper: `{"PEER_ADDRESS": "10.0.0.1", "PEER_AS": 65001}`
- Huawei: `{"BGP_PEER_IP": "10.0.0.1", "REMOTE_AS": 65001}`
- **Normalized**: `{"peer_ip": "10.0.0.1", "peer_as": 65001}`

---

# Part 1: TextFSM Template Generator

## Purpose

Automatically generate high-quality TextFSM parsing templates using an iterative ReAct loop with Pydantic constraint validation. Triggered when templates are missing, poor quality (<80% extraction), or explicitly requested.

## Trigger Mechanism

- **Automatic**: Template missing, extraction rate <80%, placeholder detected
- **Manual**: User requests template generation for a specific command
- **Automatic**: Format detection trigger when `[TextFSM Failed]` in logs

## Generation Process (ReAct Loop)

**Iteration 1 - Initial Generation**:
1. Analyze raw output structure (headers, records, patterns)
2. Identify field positions and value patterns
3. Generate TextFSM template with header and value patterns
4. Test on sample output
5. Validate syntax and Pydantic constraints

**Iteration 2-N - Refinement**:
- Analyze extraction results
- Fix failing patterns or invalid state names
- Re-test until success or max iterations
- Report quality metrics

## Quality Metrics

| Extraction Rate | >80% | ✅ Accept |
| Extraction Rate | 50-80% | ⚠️ Refine |
| Extraction Rate | <50% | 🔄 Regenerate |
| Pydantic Validation | Pass | ✅ Accept |
| Syntax Validation | Pass | ✅ Accept |

## Template Structure

Example auto-generated TextFSM template:

```textfsm
# Auto-generated TextFSM Template
# Generated: 2026-01-20
# Extraction Rate: 95% | Quality Score: 0.95

Value BGP_NEIGHBOR \S+
Value NEIGHBOR_AS \d+
Value STATE \S+

START
  ^BGP neighbor is ${BGP_NEIGHBOR},.* remote AS ${NEIGHBOR_AS}, ${STATE}$ -> PARSE_INFO

PARSE_INFO
  ^  state is ${STATE}$
  ^  Last read -> Record
```

## Example Output

---

# Part 2: Field Mapping Learner

## Purpose

Automatically discover and learn field name mappings between vendor-specific TextFSM outputs and OLAV's standardized Pydantic models.

## Trigger Mechanism

- **Automatic**: Unknown platform+command combination encountered
- **Automatic**: Field mapping missing in cache
- **Automatic**: Low confidence in existing mapping (<0.80)
- **Manual**: User requests field mapping creation

## Learning Process

### Step 1: Semantic Analysis
- Extract field names from TextFSM output
- Analyze semantic meaning (BGP_NEIGHBOR → peer_ip)
- Identify target Pydantic model fields
- Generate candidate mappings with confidence scores

### Step 2: Confidence Scoring

**Factors increasing confidence**:
- Semantic similarity (exact/fuzzy match)
- Data type validation (IP format, number format)
- Context awareness (command type, platform)
- Pattern recognition (common field names)

**Confidence Levels**:
- **High (>0.90)**: Auto-apply
- **Medium (0.80-0.90)**: Apply with warning flag
- **Low (<0.80)**: Require manual review

### Step 3: Validation
- Test mapping on sample data
- Validate with Pydantic model
- Cache successful mappings
- Log failures for analysis

## Mapping Storage

Learned mappings cached in `.olav/config/mappings/`:

```json
{
  "platform": "cisco_ios",
  "command": "show_bgp_summary",
  "learned_at": "2026-01-20T10:30:00Z",
  "confidence": 0.95,
  "mappings": {
    "BGP_NEIGHBOR": "peer_ip",
    "NEIGHBOR_AS": "peer_as",
    "STATE": "status"
  }
}
```

---

# Part 3: End-to-End Integration

## Complete Workflow

```python
# Step 1: Execute command on device
raw_output = nornir_execute("cisco_ios", "show bgp summary")

# Step 2: Check for template (generate if missing/poor quality)
template = find_or_generate_template("cisco_ios", "show_bgp_summary", raw_output)

# Step 3: Parse with TextFSM
parsed_data = parse_with_textfsm(raw_output, template)
# Result: {"BGP_NEIGHBOR": "10.0.0.1", "NEIGHBOR_AS": 65001}

# Step 4: Check for field mapping (learn if missing)
mapping = find_or_learn_mapping("cisco_ios", "show_bgp_summary", parsed_data)

# Step 5: Normalize with mapping
normalized = apply_mapping(parsed_data, mapping)
# Result: {"peer_ip": "10.0.0.1", "peer_as": 65001}

# Step 6: Validate with Pydantic
bgp_peer = BGPNeighbor(**normalized)  # ✅ Success
```

## Usage Examples

```
User: "Generate TextFSM parser for Huawei BGP command"
→ Analyzes raw output → Generates template → Validates with Pydantic

User: "Parse this output and normalize to standard model"
→ Checks template → Parses → Learns mapping → Returns Pydantic model

User: "Teach me the field mappings for Juniper"
→ Analyzes Juniper fields → Matches to standard model → Caches mappings
```

---

# Configuration & Maintenance

## Template Directory

```
.olav/config/textfsm/
├── cisco_ios_show_bgp_summary.textfsm
├── huawei_display_bgp_peer.textfsm
└── ...
```

## Mapping Directory

```
.olav/config/mappings/
├── cisco_ios_show_bgp_summary.json
├── huawei_display_bgp_peer.json
└── ...
```

---

# Quality Assurance

**Template Quality Checks**:
- ✅ Extraction rate >80%
- ✅ Pydantic validation passes
- ✅ No regex syntax errors
- ✅ All required fields extracted

**Mapping Quality Checks**:
- ✅ Confidence score >0.80
- ✅ Semantic similarity validated
- ✅ Cross-vendor consistency
- ✅ No ambiguous mappings

---

# Known Improvements (P1)

- **Multi-model parsing**: Support for complex hierarchical outputs
- **Template versioning**: Track template history and quality metrics
- **Cross-vendor validation**: Auto-validate mappings across vendors
- **Interactive refinement**: User feedback loop for template improvement
- **Performance optimization**: Cache compiled templates and reduce compilation time
- **Template library**: Expand community-contributed parser templates
