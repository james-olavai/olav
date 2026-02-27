# 🏗️ Multi-Agent Federated Architecture (v0.10.x)

To balance **speed (Fast Path)**, **accuracy (Deep Analysis)**, and **control (CLI Fallback)**, OLAV 0.10.x adopts a Federated Multi-Agent Architecture.

---

## 1. The Multi-Agent Strategy

We move away from a single "God-Agent" to a specialized medical-consultation-style model: **One Orchestrator + Multiple Specialists**.

### 1.1 Intent Routing (Tier 1)
The **Orchestrator** acts as a Zero-Shot router. It classifies intents in < 2 seconds:
- **Fast SQL Path**: "Show me all BGP neighbors" -> Translated directly to SQL, no reasoning loop.
- **Fast CLI Path**: "Run 'show clock' on R1" -> Direct command execution.
- **Expert Path**: "Why is R1 to R3 failing?" -> Delegate to the Specialist Matrix.

### 1.2 Specialist Matrix (Tier 2)
Each Specialist has a narrow, deep focus. Their System Prompts are isolated to reduce context-bloat and hallucinations.

| SubAgent | Expertise | Context (Tables/Tools) |
| :--- | :--- | :--- |
| **olav-config** | Ingestion & Administration | `devices`, `parsed_outputs` (Raw writing), DB Cleanup/Init |
| **olav-discovery** | Logical Synthesis (DB Agent) | Builds `topology_links`, `bgp_neighbors`, `routes` from raw data |
| **Specialist-Routing** | Reachability & Protocols | Analysis of `v_routes_enriched`, `bgp_routes` |
| **Specialist-Topology** | Path Analysis | Analysis of `topology_links`, `interfaces` |
| **Specialist-Probe** | Live Reconnaissance | `execute_cli_parallel`, `ping`, `traceroute` |

---

## 2. File & Output Management: The "Post-Office" Pattern

### 2.1 The Architectural Decision: Orchestrator as the Output Gateway

**Core Rule**: **All cross-cutting output formatting (CSV, PDF, Markdown reports) and file persistence are handled ONLY by the Orchestrator.**

#### Why?
1. **Specialist Simplicity**: Keep subagents focused on *Logic*. They shouldn't care if the user wants a CSV or a Terminal table. They just return structured JSON.
2. **Persistence Safety**: The Orchestrator has a unified view of the `exports/` directory. It ensures that output files from multiple specialists are consolidated (e.g., merging a topology report and a BGP report into one `summary.md`).
3. **Consistency**: Formatting logic (e.g., date-based folders, unique naming) is maintained in one place (`format_and_export` tool).

#### The Workflow:
1. **Ingestion (`olav-config`)**: SSH to Raw text (writes `parsed_outputs`). Handles DB Reset.
2. **Synthesis (`olav-discovery`)**: Reads `parsed_outputs`, writes entity tables (Topology/Neighbors).
3. **Analysis (`Specialist-*`)**: Reads entities to generate results.
4. **Export (`Orchestrator`)**: Receives data, calls `format_and_export`, writes report to `exports/`.

---

## 3. Native DeepAgents Implementation

OLAV leverages `OLAV.md` (YAML frontmatter) to define this federation.

```yaml
# Simplified OLAV.md Example
orchestrator:
  prompt: orchestrator_system.md
  skills: [common-tools]
  include_tools: [format_and_export] # Orchestrator handles files

subagents:
  - name: specialist-routing
    description: Expert in BGP, OSPF, and Routing Tables.
    skills: [routing-tools]
    prompt: routing_subagent.md
  
  - name: specialist-topology
    description: Expert in physical connectivity and path analysis.
    skills: [topology-tools]
    prompt: topology_subagent.md
```

### 3.1 Agent Switching in CLI
Users can explicitly switch contexts using `deepagents-cli` native commands:
- `olav --agent sql`: Starts in high-speed SQL mode.
- `olav --agent audit`: Focuses on governance and compliance checks.
- `olav`: Starts the Orchestrator for complex, multi-expert queries.


---

## 4. Building the Digital Twin: Modeling & Time-Series

OLAV transcends basic query bots by maintaining a deep, historical representation of the network state.

### 4.1 Schema Normalization via "Fuzzy Mapping"
Hardcoding parsers for every vendor (`Cisco=Up`, `Huawei=EST`) is unsustainable. 
- **The Baseline**: OLAV uses **Cisco IOS/NXOS** patterns as its universal internal schema.
- **LLM Translator Engine**: When `olav-discovery` encounters unknown vendor data, it uses an LLM to map foreign keys to the Cisco baseline.
- **Persistent Memory**: Once the LLM successfully maps a vendor's output (e.g., Huawei `est` -> Cisco `up`), it saves this rule to a `schema_mappings` table. Future parses bypass the LLM, ensuring zero-latency ingestion.

### 4.2 Time-Series Architecture (`snapshot_id`)
To answer questions like *"What went wrong at 3 AM?"*, OLAV must retain history.
- **Append-Only DB**: Tables like `topology_links`, `bgp_routes`, and `interfaces` no longer use UPSERT. They are append-only.
- **Snapshot Tracking**: Every inserted row includes a `snapshot_id` (timestamp hash).
- **Default State**: By default, all Analysis Specialists (`Specialist-Routing`, etc.) append `WHERE snapshot_id = (SELECT MAX(snapshot_id)...)` to their SQL queries, viewing only the *current* state unless asked otherwise.

### 4.3 Multidimensional Diffing: The `Specialist-Diff`
Text diffs (++ / --) of config files are hard to read for complex bridging issues. `Specialist-Diff` (olav-diff) operates at the database level:
1. **Control-Plane Delta**: "Which BGP routes disappeared between T1 and T2?"
2. **Topology Delta**: "Which CDP adjacency went down?"
3. **Config Delta**: Raw text comparison when needed.

This provides instant, root-cause correlation (e.g., "The interface went down, which destroyed the BGP session and withdrew 15 routes").

---

## 5. Realistic Scenario: Multi-Device Command Capture

**User**: "Run 'show run' on all routers and save to individual output files."

1. **Orchestrator**: Recognizes a multi-device command task.
2. **Delegation**: Calls `Specialist-Probe` to execute `execute_cli_parallel`.
3. **Execution**: `Specialist-Probe` returns a massive dictionary of `{device_name: raw_text}`.
4. **Resolution**: Orchestrator takes this result and uses its internal `write_file` or `format_and_export` logic to iterate through the dictionary and create:
   - `data/exports/show_run/R1.txt`
   - `data/exports/show_run/R2.txt`
   - ...

This keeps the specialists "lean" and the system "organized".
