---
name: Security Guard
id: guard
description: "Security Gatekeeper - Pre-execution safety checks (dangerous commands, config changes, sensitive data)"
version: 1.0.0
intent: security
complexity: simple
enabled: true

# Configuration
config:
  language: zh  # Message language: zh or en
  llm_classification:
    enabled: false  # LLM intent classification (for complex scenarios)
    fallback_only: true  # Use LLM only when pattern matching fails
  cache_enabled: true  # Cache guard decisions for repeated queries

# Action types (defined here, not hardcoded)
actions:
  - name: pass
    description: "Allow execution without restrictions"
  - name: reject
    description: "Block immediately, no execution"
  - name: require_approval
    description: "Require user confirmation (HITL)"
  - name: warn
    description: "Warning but allow execution"

# Severity levels (defined here, not hardcoded)
severities:
  - critical  # Immediate rejection
  - high      # Require approval
  - medium    # Warning
  - low       # Informational
---

# Security Guard

## Role

You are a Security Gatekeeper responsible for pre-execution safety checks. Your primary function is to detect and prevent dangerous operations before they reach the Orchestrator.

**Core Responsibilities**:
1. **Dangerous Command Detection**: Block commands that could cause system damage (reload, reboot, erase, format)
2. **Configuration Change Control**: Require approval for config modifications (write memory, copy config)
3. **Sensitive Data Protection**: Flag operations involving passwords, keys, credentials
4. **Whitelist Management**: Fast-path safe commands without deep inspection

## Workflow

```
User Input → Guard Check → [pass / reject / require_approval / warn] → Orchestrator
             ↑
             rules.yaml (pattern-based)
             whitelist.yaml (fast-path)
             LLM (complex scenarios, optional)
```

## Rule Structure

### Pattern-based Rules (rules.yaml)

Rules are categorized by threat type:
- **dangerous_commands**: Immediate rejection (critical severity)
- **config_changes**: Require approval (high severity)
- **sensitive_data**: Require confirmation (high severity)
- **network_impact**: Warning (medium severity)

Each rule contains:
```yaml
- pattern: "(regex pattern)"
  action: reject | require_approval | warn | pass
  message:
    en: "English message"
    zh: "中文消息"
  severity: critical | high | medium | low
```

### Whitelist (whitelist.yaml)

Fast-path for safe commands:
- Command prefixes: ["show", "list", "get", "display"]
- Read-only operations
- Query operations

## Processing Logic

### Step 1: Whitelist Check (Fast-path)
- Check if command matches whitelist prefixes
- If matched → **pass** (skip pattern matching)

### Step 2: Pattern Matching (Deterministic)
- Apply regex rules from rules.yaml
- Match found → Execute action (reject/require_approval/warn)
- No match → Continue to Step 3

### Step 3: LLM Classification (Optional)
- Enabled only if `config.llm_classification.enabled: true`
- Analyze complex queries with ambiguous intent
- Provide context-aware threat assessment
- **Not implemented yet** (reserved for future)

### Step 4: Default Action
- If all checks pass → **pass**

## Integration with Orchestrator

Guard runs **before** Orchestrator:
```python
# In cli_main.py or API entry point
guard = Guard(config_path=".olav/skills/guard/rules.yaml")
result = guard.check(user_input)

if result.action == "reject":
    return result.message  # Block execution

if result.action == "require_approval":
    confirmed = await ask_user_confirmation(result.message)
    if not confirmed:
        return "Operation cancelled"

if result.action == "warn":
    display_warning(result.message)

# Continue to Orchestrator
orchestrator = create_orchestrator()
orchestrator.ainvoke(user_input)
```

## Performance Optimization

### Caching
- Cache guard decisions for repeated queries (LRU 1000 entries)
- Cache key: MD5 hash of user input
- Clear cache when rules.yaml modified

### Fast-path
- Whitelist check before pattern matching (O(1) vs O(n))
- Precompile regex patterns at startup

## Configuration Files

### rules.yaml
Location: `.olav/skills/guard/rules.yaml`

Contains:
- Pattern definitions (regex)
- Action types (reject/require_approval/warn)
- Message templates (bilingual)
- Severity levels

### whitelist.yaml
Location: `.olav/skills/guard/whitelist.yaml`

Contains:
- Command prefixes (safe operations)
- Whitelisted patterns (read-only queries)

## Examples

### Example 1: Block Dangerous Command
```
User: "reload the router"
Guard: ⛔ Dangerous command blocked: reload
Action: reject
```

### Example 2: Require Approval
```
User: "write memory"
Guard: ⚠️ Saving configuration requires approval
Action: require_approval
Prompt: [Y/n]
```

### Example 3: Warning
```
User: "show running-config with passwords"
Guard: ⚠️ Sensitive data may be exposed
Action: warn
Continue: Yes
```

### Example 4: Pass (Whitelist)
```
User: "show ip interface brief"
Guard: ✅ Whitelisted command
Action: pass (fast-path)
```

## Error Handling

### Missing Rules File
- Fallback to default rules (reject dangerous commands only)
- Log warning: "Guard rules not found, using defaults"

### Invalid Rule Format
- Skip invalid rules
- Log error: "Invalid rule at line X: {error}"

### LLM Classification Failure
- Fallback to pattern matching
- Log error: "LLM classification failed: {error}"

## Future Enhancements

### LLM Intent Classification
- Implement semantic threat detection
- Context-aware security analysis
- Learn from user feedback (approve/reject patterns)

### User-specific Rules
- Per-user whitelist/blacklist
- Role-based access control (RBAC)
- Audit logs for sensitive operations

### Machine Learning
- Anomaly detection (unusual command patterns)
- Behavioral analysis (detect suspicious sequences)
- Auto-tuning rule thresholds

## Integration Points

### With Orchestrator
- Guard runs before Orchestrator
- Pass GuardResult metadata to Orchestrator (for audit logs)

### With CLI
- cli_main.py imports Guard directly
- Display guard messages in CLI UI
- Prompt user for confirmation (require_approval)

### With API
- API server wraps Guard around endpoints
- Return HTTP 403 for rejected commands
- Return HTTP 202 for require_approval (with approval token)

## Testing

### Unit Tests
- Test each rule category (dangerous_commands, config_changes, etc.)
- Test whitelist fast-path
- Test message localization (zh/en)

### Integration Tests
- Test Guard + Orchestrator flow
- Test Guard + CLI flow
- Test Guard + API flow

### Performance Tests
- Test caching effectiveness (cache hit rate)
- Test regex compilation overhead
- Test fast-path vs pattern matching speed

## Maintenance

### Adding New Rules
1. Edit `.olav/skills/guard/rules.yaml`
2. Add pattern, action, message, severity
3. Test with sample inputs
4. Commit to version control

### Updating Messages
1. Edit message templates in rules.yaml
2. Test bilingual messages (zh/en)
3. Ensure consistency across rules

### Tuning Performance
1. Monitor cache hit rate
2. Optimize regex patterns (avoid backtracking)
3. Adjust cache size (LRU limit)

## Security Best Practices

1. **Defense in Depth**: Guard is first line of defense, not the only one
2. **Fail Secure**: Default to reject when uncertain
3. **User Confirmation**: Require approval for high-impact operations
4. **Audit Logging**: Log all guard decisions (for forensics)
5. **Regular Updates**: Update rules based on new threats
