# TextFSM Templates for OLAV

This directory contains TextFSM templates for parsing network device CLI output into structured data.

## 📋 Overview

TextFSM (Text Finite State Machine) is a Python library for parsing semi-formatted text. These templates convert CLI output from human-readable text into machine-parseable JSON/dictionaries.

## 🗂️ Template Collection

### Cisco IOS/IOS-XE
- `cisco_ios_show_interfaces.textfsm` - Interface details (status, stats, config)
- `cisco_ios_show_ip_interface_brief.textfsm` - Interface summary
- `cisco_ios_show_version.textfsm` - Device version and hardware info
- `cisco_ios_show_ip_ospf_neighbor.textfsm` - OSPF neighbor relationships
- `cisco_ios_show_ip_bgp_summary.textfsm` - BGP session summary
- `cisco_ios_show_processes_cpu.textfsm` - CPU utilization and processes

### Coverage Statistics
- **Total templates**: 10
- **Platform coverage**: Cisco IOS/IOS-XE, IOS-XR, Huawei VRP, Linux
- **Command categories**: Interface, Routing, System, Performance

## 🎯 Usage

### Automatic (via Netmiko)

OLAV automatically uses these templates when `use_textfsm=True`:

```python
from olav.tools.network_executor import NetworkExecutor

executor = NetworkExecutor()
result = executor.execute_with_parsing(
    device="R1",
    command="show ip interface brief",
    use_textfsm=True  # Auto-parsed with template
)

print(result.structured)  # True
print(result.output)      # JSON structured data
```

### Manual (via textfsm library)

```python
import textfsm
from pathlib import Path

template_path = Path(".olav/templates/cisco_ios_show_version.textfsm")
cli_output = "..."  # Raw CLI output

with template_path.open() as f:
    template = textfsm.TextFSM(f)
    parsed = template.ParseText(cli_output)
    
print(parsed)  # List of parsed records
```

## 🔧 Environment Configuration

Set the template directory in your environment:

```bash
# .env
NET_TEXTFSM=/home/yhvh/Olav/.olav/templates
```

Or configure dynamically in code:

```python
import os
from pathlib import Path

os.environ["NET_TEXTFSM"] = str(Path(".olav/templates").resolve())
```

## 📚 Template Format

TextFSM templates use a state machine approach:

```
Value Required INTERFACE (\S+)        # Define value to extract
Value STATUS (up|down)                # Regex captures value

Start                                 # Initial state
  ^${INTERFACE}\s+is\s+${STATUS} -> Record  # Match pattern, extract, record
```

**Key elements**:
- `Value`: Define variables to extract
- `Required`: Must match for record to be valid
- `List`: Allow multiple values for this variable
- `Start`: Initial parsing state
- `${VARIABLE}`: Reference to extract value
- `-> Record`: Save current values as a record

## 🎨 Token Savings

TextFSM parsing significantly reduces LLM token consumption:

| Command | Raw Tokens | Parsed Tokens | Savings |
|---------|------------|---------------|---------|
| show interfaces | ~2000 | ~600 | 70% |
| show ip ospf neighbor | ~1500 | ~500 | 67% |
| show processes cpu | ~1000 | ~400 | 60% |
| **Average** | **1500** | **500** | **66%** |

## ➕ Adding New Templates

### 1. Create Template File

```bash
# Create new template
touch .olav/templates/cisco_ios_show_ip_route.textfsm
```

### 2. Define Values and Pattern

```
Value PROTOCOL (\S+)
Value NETWORK (\d+\.\d+\.\d+\.\d+)
Value MASK (\d+\.\d+\.\d+\.\d+)
Value NEXT_HOP (\d+\.\d+\.\d+\.\d+)

Start
  ^${PROTOCOL}\s+${NETWORK}\s+${MASK}\s+\[\d+/\d+\]\s+via\s+${NEXT_HOP} -> Record
```

### 3. Update Index

```bash
# Add to index file
echo "cisco_ios_show_ip_route.textfsm, .*, cisco_ios, sh[[ow]] ip rou[[te]]" >> .olav/templates/index
```

### 4. Test Template

```python
from olav.tools.network_executor import NetworkExecutor

executor = NetworkExecutor()
result = executor.execute_with_parsing(
    device="R1",
    command="show ip route",
    use_textfsm=True
)

assert result.structured == True
assert result.tokens_saved > 0
```

## 🔍 Template Testing

Test templates with sample CLI output:

```python
import textfsm

template_file = ".olav/templates/cisco_ios_show_version.textfsm"
sample_output = """
Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE11
ROM: Bootstrap program is C2960 boot loader
BOOTLDR: C2960 Boot Loader (C2960-HBOOT-M) Version 12.2(55r)SE12
Router uptime is 2 weeks, 3 days, 4 hours, 26 minutes
System image file is "flash:c2960-lanbasek9-mz.150-2.SE11.bin"
Processor board ID FOC1234X5YZ
Configuration register is 0xF
"""

with open(template_file) as f:
    template = textfsm.TextFSM(f)
    result = template.ParseText(sample_output)
    
print(result)
# [['15.0(2)SE11', 'C2960', ..., '0xF']]
```

## 🌐 Resources

- **TextFSM Documentation**: https://github.com/google/textfsm
- **NTC Templates**: https://github.com/networktocode/ntc-templates (20k+ stars)
- **Template Testing Tool**: https://textfsm.nornir.tech/

## ⚠️ Fallback Behavior

When no template exists or parsing fails:
- OLAV automatically falls back to raw text output
- Query continues without error
- Logs warning for template improvement
- See: `config/settings.py` → `textfsm_fallback_to_raw`

## 📝 Notes

- Templates are case-sensitive in Value names
- Use `List` for multiple occurrences (e.g., interface lists)
- Test templates with diverse CLI outputs
- Keep patterns specific but flexible
- Document complex regex patterns

---

**Version**: 1.0.0  
**Last Updated**: 2026-02-11  
**Maintained by**: OLAV Core Team
