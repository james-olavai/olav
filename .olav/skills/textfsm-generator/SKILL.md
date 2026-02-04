---
name: Template Tools
description: Automated TextFSM template generation and field mapping learning for cross-vendor data normalization. Use when system needs new parsers, field mappings, or user asks to "generate template", "learn field mapping", "create parser".
version: 2.0.0

# OLAV Extended Fields
intent: self-learning
complexity: advanced

# Trigger Conditions
triggers:
  automatic:
    - TextFSM parsing fails with "No template found"
    - Extraction rate < 50% (poor template quality)
    - Placeholder template detected
    - Field mapping missing in field_mappings.py
  manual:
    - "User query: generate template"
    - "User query: create parser"
    - "User query: textfsm template"
    - "User query: learn field mapping"
    - "User query: create mapping"
    - "User query: normalize vendor data"

# Constraints
constraints:
  max_iterations: 5              # Maximum ReAct loops for template generation
  min_extraction_rate: 0.8       # Minimum 80% record extraction
  min_confidence: 0.8            # Minimum LLM confidence for field mappings
  require_human_review: true     # Requires user approval before use
  pydantic_validation: true      # Must pass Pydantic constraint validation
  cache_mappings: true           # Persist learned mappings
  support_fuzzy_match: true      # Handle similar field names

# Output Configuration
output:
  templates:
    format: textfsm
    location: .olav/config/textfsm/
    metadata: true               # Generate .meta file with quality score
  mappings:
    format: json
    location: .olav/config/mappings/
    update_code: false            # Don't modify field_mappings.py directly

# Phase 4.7 E2E Test Findings (2026-02-04)
# ============================================
# Status: ✅ Skill integration verified, quality improvements needed
#
# Test Results:
# - test_textfsm_self_learning_e2e: Added comprehensive E2E test
# - Template generation success rate: <40% (LLM quality issue)
# - Common errors: "Invalid state name" (TextFSM syntax errors)
# - Current iteration count: 5 max (insufficient for <40% success)
#
# Problems Identified:
# 1. LLM TextFSM syntax generation quality is poor
#    - Generates invalid state names like "^${INTERFACE}\s+"
#    - Missing proper FSM state transitions
#    - Incorrect template structure (line breaks in wrong places)
#
# 2. Prompt engineering needs improvement
#    - Current prompt doesn't enforce TextFSM syntax strictly
#    - No syntax validation in generation loop
#    - No examples of working TextFSM templates
#
# 3. Iteration strategy needs enhancement
#    - 5 iterations not sufficient for <40% success rate
#    - No feedback mechanism from TextFSM parser
#    - No validation of generated template structure
#
# Future Improvements (P1):
# 1. Add TextFSM syntax validation step
#    - Validate generated template with textfsm.TextFSM(StringIO(template))
#    - Catch and report syntax errors to LLM
#    - Iterate on syntax errors instead of extraction errors
#
# 2. Enhance LLM prompt with examples
#    - Include 3-5 working TextFSM templates as examples
#    - Show correct syntax for complex patterns
#    - Emphasize state transition rules
#
# 3. Increase iteration limit conditionally
#    - If syntax error: retry with feedback (max 10 iterations)
#    - If extraction error: use current 5-iteration limit
#    - Track failure reason for better error reporting
#
# 4. Implement template quality scoring
#    - Check parsing accuracy on sample data
#    - Generate quality metadata (.meta file)
#    - Warn user if quality <50% before saving
#
# Test Coverage:
# - test_coder_agent_textfsm_generation: ✅ PASSED
# - test_textfsm_self_learning_e2e: ✅ IMPLEMENTED (skipped due to quality)
# - Integration with skill system: ✅ VERIFIED
---

# Template Tools (TextFSM Generation & Field Mapping Learning)

## Overview


This skill provides two complementary self-learning capabilities:
1. **TextFSM Template Generator** - Automatically generate parsing templates
2. **Field Mapping Learner** - Learn cross-vendor field name mappings

## Architecture

```
Data Normalization Pipeline:

  Raw Command Output (vendor-specific)
       │
       ├─ Cisco: "show bgp summary"
       ├─ Juniper: "show bgp neighbor"
       └─ Huawei: "display bgp peer"
       │
       ▼
  [TextFSM Template Generator]
       │
       ├─ Template exists? → Use it ✓
       ├─ Placeholder template? → Generate full template
       └─ No template? → Generate new template
       │
       ▼
  TextFSM Parsed Data (vendor-specific fields)
       │
       ├─ {"BGP_NEIGHBOR": "10.0.0.1", "NEIGHBOR_AS": 65001}      (Cisco)
       ├─ {"PEER_ADDRESS": "10.0.0.1", "PEER_AS": 65001}         (Juniper)
       └─ {"BGP_PEER_IP": "10.0.0.1", "REMOTE_AS_NUMBER": 65001} (Huawei)
       │
       ▼
  [Field Mapping Learner]
       │
       ├─ Mapping exists? → Use it ✓
       └─ Mapping missing? → Learn new mapping
       │
       ▼
  Normalized Data (standardized Pydantic models)
       │
       └─ {"peer_ip": "10.0.0.1", "peer_as": 65001}  ✓
```

---

# Part 1: TextFSM Template Generator

## Purpose

Automatically generate TextFSM parsing templates for network device commands that lack existing parsers. Uses ReAct (Reasoning + Acting) loops with Pydantic constraint validation to ensure high-quality template generation.

## Trigger Mechanism

### Automatic Triggers
- Parsing fails with "No template found"
- Extraction rate < 50% (poor template quality)
- Placeholder template detected (v0.9.0 feature)

### Manual Triggers
- User explicitly requests template generation
- `/command` execution with placeholder template

### Placeholder Template (v0.9.0)

Users can create placeholder templates to trigger auto-generation:

```textfsm
# PLACEHOLDER: Auto-generate template for this command
# Platform: cisco_ios
# Command: show ip msdp peer
# Created: 2026-01-15
#
# This file will be replaced by auto-generated template after
# first successful /command execution with raw output.

Value List (\.)
```

## Generation Process (ReAct Loop)

### Iteration 1: Initial Template
1. **Analyze** raw output structure
2. **Identify** record patterns (header, values, repeat)
3. **Generate** TextFSM template with:
   - Header pattern (column names)
   - Value pattern (data extraction)
   - Repeat rules (multi-record)
4. **Test** against sample output
5. **Validate** with Pydantic constraints

### Iteration 2-N: Refinement
- **Fail** → Analyze errors
- **Adjust** regex patterns
- **Re-test** until success or max iterations

## Quality Metrics

| Metric | Threshold | Action |
|--------|-----------|--------|
| Extraction Rate | >80% | Accept |
| Extraction Rate | 50-80% | Refine (ReAct) |
| Extraction Rate | <50% | Regenerate |
| Pydantic Validation | Pass | Accept |
| Pydantic Validation | Fail | Refine |

## Template Structure

```textfsm
# Auto-generated TextFSM Template
# Platform: {{platform}}
# Command: {{command}}
# Generated: {{timestamp}}
# Quality Score: {{score}} (extraction_rate * validation_pass)

Value List (\*)

{{header_pattern}}

{{start}}

{{value_pattern}}

{{end_pattern}}
```

## Example Output

```textfsm
# Auto-generated for: cisco_ios_show_bgp_summary
# Platform: cisco_ios
# Command: show bgp summary
# Quality Score: 0.95 (95% extraction, validation passed)

Value BGP_NEIGHBOR NEIGHBOR_AS STATE UPTIME_COUNT (\d+)
Value MSINPUT_COUNT (\d+)

BGP neighbor is {{BGP_NEIGHBOR}}, remote AS {{NEIGHBOR_AS}}, {{STATE}}
BGP version 4, remote router ID {{ID}}, state {{STATE}}
  uptime is {{UPTIME}}
  Last read {{MSINPUT_COUNT}}:00:00

Start = 1
End

^BGP neighbor is ${BGP_NEIGHBOR},.* remote AS ${NEIGHBOR_AS}, ${STATE}$
^.* state ${STATE}$
^  uptime is ${UPTIME}$
^  Last read ${MSINPUT_COUNT}:
```

---

# Part 2: Field Mapping Learner

## Purpose

Automatically discover and learn field name mappings between vendor-specific TextFSM outputs and OLAV's standardized Pydantic models. Eliminates the need for manual mapping table maintenance when adding support for new vendors or commands.

## Trigger Mechanism

### Automatic Triggers
- Normalizer encounters unknown platform+command combination
- Field mapping missing in field_mappings.py
- Low confidence in existing mapping (<0.8)

### Manual Triggers
- User requests field mapping creation
- User asks to normalize vendor data

## Learning Process

### Step 1: Semantic Analysis
1. **Extract** field names from TextFSM output
2. **Analyze** semantic meaning using LLM
3. **Identify** target Pydantic model fields
4. **Generate** candidate mappings

### Step 2: Confidence Scoring

Factors that increase confidence:
- Semantic similarity (BGP_NEIGHBOR → peer_ip)
- Pattern matching (contains common terms)
- Data type validation (IP address format)
- Context awareness (command type)

Confidence levels:
- **High (>0.9)**: Auto-apply
- **Medium (0.8-0.9)**: Apply with warning
- **Low (<0.8)**: Require manual review

### Step 3: Validation

```python
# Pseudocode
for source_field, target_field, confidence in mappings:
    # Test mapping on sample data
    try:
        normalized = apply_mapping(raw_data, {source_field: target_field})
        pydantic_model(**normalized)
        # Success: mapping is valid
        cache_mapping(source_field, target_field, confidence)
    except ValidationError:
        # Failure: mapping is invalid
        log_error(source_field, target_field)
```

## Mapping Storage

Learned mappings are cached in `.olav/config/mappings/`:

```json
{
  "platform": "cisco_ios",
  "command": "show_bgp_summary",
  "mappings": {
    "BGP_NEIGHBOR": {
      "target": "peer_ip",
      "confidence": 0.95,
      "learned_at": "2026-01-16T10:30:00Z",
      "validated": true
    },
    "NEIGHBOR_AS": {
      "target": "peer_as",
      "confidence": 0.98,
      "learned_at": "2026-01-16T10:30:00Z",
      "validated": true
    }
  },
  "fuzzy_matches": {
    "BGP_PEER_IP": "peer_ip",
    "PEER_ADDRESS": "peer_ip",
    "REMOTE_AS": "peer_as"
  }
}
```

## Fuzzy Matching

Supports fuzzy matching for similar field names:

| Source Field | Fuzzy Match | Confidence |
|--------------|-------------|------------|
| BGP_NEIGHBOR | peer_ip | 0.95 |
| BGP_PEER_IP | peer_ip | 0.92 |
| PEER_ADDRESS | peer_ip | 0.89 |
| REMOTE_AS_NUMBER | peer_as | 0.91 |
| NEIGHBOR_AS | peer_as | 0.98 |

---

# Part 3: Integration Workflow

## End-to-End Example

```python
# Step 1: Execute command on new platform
raw_output = nornir_execute("huawei", "display bgp peer")

# Step 2: Check for template
template = find_template("huawei", "display bgp peer")
if template is None or is_placeholder(template):
    # TRIGGER: TextFSM Template Generator
    template = generate_template(raw_output, platform="huawei", command="display bgp peer")

# Step 3: Parse with template
parsed_data = parse_with_textfsm(raw_output, template)
# Result: {"BGP_PEER_IP": "10.0.0.1", "REMOTE_AS_NUMBER": 65001, ...}

# Step 4: Check for field mapping
mapping = find_mapping("huawei", "display bgp peer")
if mapping is None:
    # TRIGGER: Field Mapping Learner
    mapping = learn_mapping(parsed_data, target_model=BGPNeighbor)

# Step 5: Normalize data
normalized = apply_mapping(parsed_data, mapping)
# Result: {"peer_ip": "10.0.0.1", "peer_as": 65001, ...}

# Step 6: Validate with Pydantic
bgp_peer = BGPNeighbor(**normalized)
```

---

# Usage Examples

```
User: "Generate a TextFSM template for Huawei's display bgp peer"
→ Analyzes command output
→ Generates template using ReAct
→ Validates with Pydantic constraints
→ Saves to .olav/config/textfsm/huawei_display_bgp_peer.textfsm

User: "Learn field mappings for Juniper BGP output"
→ Analyzes Juniper field names
→ Matches to standardized model
→ Generates confidence scores
→ Caches mappings for future use

User: "Parse this Cisco output and normalize it"
→ Checks for existing template
→ Generates if missing
→ Parses with TextFSM
→ Learns field mappings if needed
→ Returns normalized Pydantic model
```

---

# Configuration Files

## Template Storage

```
.olav/config/textfsm/
├── cisco_ios/
│   ├── show_bgp_summary.textfsm
│   ├── show_interface_status.textfsm
│   └── ...
├── huawei_vrp/
│   ├── display_bgp_peer.textfsm
│   └── ...
└── juniper_junos/
    ├── show_bgp_neighbor.textfsm
    └── ...
```

## Mapping Storage

```
.olav/config/mappings/
├── cisco_ios_show_bgp_summary.json
├── huawei_display_bgp_peer.json
├── juniper_show_bgp_neighbor.json
└── ...
```

---

# Quality Assurance

## Template Quality Checks

- ✅ Extraction rate >80%
- ✅ Pydantic validation passes
- ✅ All required fields present
- ✅ Data types match constraints
- ✅ No regex syntax errors

## Mapping Quality Checks

- ✅ Confidence score >0.8
- ✅ Semantic similarity validated
- ✅ No ambiguous mappings
- ✅ Cross-vendor consistency
- ✅ Manual review for low-confidence mappings

---

# Migration Notes

This skill merges two previous skills:
- **textfsm-generator** (v1.1) → TextFSM template generation
- **field-mapping-learner** (v1.0) → Field name mapping learning

Both capabilities are now available in a unified skill that provides end-to-end data normalization support.
