# Topology visualisation (Mode 3)

Load when the user asks for a topology diagram, path analysis, or
loop detection.  Always run inside `run_python_simulation` and call
`format_and_export` to save the Mermaid as `.mmd` — never just print.

## Device resolution (mandatory)

When building L3 topologies, resolve neighbour IPs to hostnames:

```sql
SELECT b.device       AS local_device,
       b.neighbor_ip,
       b.neighbor_as,
       b.state,
       COALESCE(d.hostname, 'Unknown') AS neighbor_hostname
FROM netops.v_bgp_neighbors_auto b
LEFT JOIN netops.devices d ON b.neighbor_ip = d.ip_address
```

## Save path convention

* `exports/topology_YYYYMMDD.mmd` — generic
* `exports/topology_bgp_YYYYMMDD.mmd` — BGP overlay
* `exports/topology_l2_YYYYMMDD.mmd` — L2 only
* Pass **raw Mermaid** content (with or without code fences — the
  tool auto-strips fences for `.mmd`)
* After saving, tell the user the path

## Mermaid formatting rules

* `graph TD` (top-down) or `flowchart LR` (left-right)
* Wrap in standard Markdown code blocks:

  ````markdown
  ```mermaid
  graph TD
    ...
  ```
  ````

* Nodes: `R1["**R1**<br/>IP: 10.1.1.1"]`
* Edges with state: `R1 -->|"Gi0/0 <br/> Established"| R2`
* Visual classes:
  ```
  classDef up fill:#90EE90,stroke:#333;
  classDef down fill:#FFB6C1,stroke:#333;
  ```
* Apply `up` to Established / FULL / link_status='up';
  apply `down` to Idle / Active / DOWN.

## Per-layer view selection

| Layer | Source | Notes |
|---|---|---|
| Physical (L2) | `netops.v_l2_links_auto` | source_device / destination_device pairs |
| BGP | `netops.v_bgp_neighbors_auto` | ASN, peering IPs, session state |
| OSPF | `netops.v_ospf_neighbors_auto` | Router-ID, interface, neighbour state |

For richer overlays (interface MTU, route prefixes, etc.) JSON-extract
from `netops.parsed_outputs` — no dedicated view exists for those
concepts.

## Path / loop detection

Build the graph in networkx:

```python
import networkx as nx
G = nx.DiGraph()
for r in rows:
    G.add_edge(r['source_device'], r['destination_device'])

shortest = nx.shortest_path(G, 'R1', 'R4')
loops    = list(nx.simple_cycles(G))
islands  = [list(c) for c in nx.weakly_connected_components(G)]
```
