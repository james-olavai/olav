# Report Type: topology_diagram

## When to use
Tag: `report_type: topology_diagram`
Input: topology links data (source_device, source_interface, destination_device, destination_interface, protocol)

## Format Rules

1. Generate a **Mermaid `graph TD`** diagram showing all links.
2. Node format: `R1[R1<br>juniper_junos]` — device name + platform if available.
3. Edge format: `R1 -->|ge-0/0/2 ↔ Et0/0<br>LLDP| R3` — interfaces + protocol.
4. Group by protocol: solid lines for CDP, dashed for LLDP.
5. After the diagram, include a summary table of all links.
6. Call `format_and_export(data=<mermaid_text>, format="mmd", filename="topology")`.

## Example Output

```mermaid
graph TD
    R1[R1<br>juniper_junos] -->|ge-0/0/2 ↔ Et0/0<br>LLDP| R3[R3<br>cisco_ios]
    R2[R2<br>cisco_ios] -->|Gi2 ↔ Et0/0<br>CDP| R4[R4<br>cisco_ios]
    R3 -->|Et0/1 ↔ Et0/0<br>CDP| SW1[SW1<br>cisco_ios]
    R4 -->|Et0/1 ↔ Et0/0<br>CDP| SW2[SW2<br>cisco_ios]
```

| Source | Port | Dest | Port | Protocol |
|---|---|---|---|---|
| R1 | ge-0/0/2 | R3 | Et0/0 | LLDP |
| R2 | Gi2 | R4 | Et0/0 | CDP |

共 N 条链接

## Export
Call `format_and_export` with the Mermaid text and `format="mmd"`.
