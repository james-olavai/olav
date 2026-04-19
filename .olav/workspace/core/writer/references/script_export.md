# Report Type: script_export

## When to use
Tag: `report_type: script_export`
Input: script content (bash/python/yaml/ansible)

## Format Rules

1. Detect script type from content (shebang, keywords).
2. Call `format_and_export` with correct format:
   - `#!/bin/bash` or `set -euo` → `format="sh"`, `subdir="scripts"`
   - `#!/usr/bin/env python` or `import ` → `format="py"`, `subdir="scripts"`
   - YAML with `hosts:` or `tasks:` → `format="yml"`, `subdir="scripts"`
3. Display: saved file path + brief usage instructions.
4. Auto-generate filename from script purpose if not provided.

## Example Output

```markdown
📁 Script saved: `exports/scripts/backup_configs.sh`

**Usage:**
```bash
chmod +x exports/scripts/backup_configs.sh
./exports/scripts/backup_configs.sh --dry-run    # preview
./exports/scripts/backup_configs.sh              # execute
```

**Contents:** Backup script for 6 devices (R1-R4, SW1-SW2), platform-aware commands, error handling included.
```

## Export
Always call `format_and_export`. Never just display the script in chat.
