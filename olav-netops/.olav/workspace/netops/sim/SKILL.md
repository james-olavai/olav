---
name: sim
description: "Simulation + change planning. Designs changes (eBGP / iBGP / VLAN / etc.), runs what-if simulations against the digital twin, outputs a Markdown CHANGE PLAN ending with a ``## Change Summary`` YAML block. Does NOT compose TCF YAML directly — a deterministic Python writer (`render_tcf` skill-script) handles that."
tools:
  - run_python_simulation
  - execute_skill_script
  - format_and_export
static_context_mode: on_intent
system: $ref:./prompts/system.md
metadata:
  version: 1.0.0
  type: agent
  network_isolation: "true"
  category: network-operations
  intents:
    - change_simulation
    - change_planning
    - what_if_analysis
    - feasibility_check
---

## Sim — write-side analysis

R-AGENT-HIERARCHY Phase B+C (2026-05-09): split out from
`analyze` (which keeps drift / topology Q&A / read-side investigation).
`sim` owns forward-looking analysis: simulating proposed changes,
checking feasibility, and writing the **change plan** in prose.

## Workflow

1. **Understand the request** — what change is the user asking for?
2. **Query DB to verify feasibility** (via `run_python_simulation`):
   * Devices exist?
   * For ebgp_direct: are ASNs different?  (Same-AS → blocker.)
   * For multihop eBGP: is there an IGP carrying loopbacks?
   * For VLAN add: is there an L2 path between target devices?
3. **Optional: run a what-if simulation** to predict impact
   (link-down blast radius, routing changes, convergence time).
4. **Write the change plan** as Markdown.  End with a fenced
   ``## Change Summary`` YAML block:

       ## Change Summary
       ```yaml
       change_id: r2-r3-ebgp
       title: Add eBGP between R2 and R3
       intent_type: ebgp_direct
       devices: [R2, R3]
       feasibility: OK             # or BLOCKED with feasibility_reason
       ```

5. **Render TCF** by invoking the `render_tcf` skill-script:

       execute_skill_script("render_tcf.py", script_args={
           "plan_text": <the entire markdown plan from step 4>,
           "output_dir": "exports/cab",
       })

   The script parses the Summary block, queries the DB for
   ASN / loopback / platform per device, renders deterministic
   CLI from intent + platform templates, and writes the TCF YAML.
   Returns: `{"status": "ok", "spec_path": "...", "facts": {...}}`
   or `{"status": "error", "error": "...", "blockers": [...]}`.

6. **Report** spec_path + facts to user.  Mention any DB gaps
   (None values in `facts`) so they're aware before lab apply.

## HARD RULES — what you DO NOT do

* You do NOT compose TCF YAML or call any TCF-emitter tool yourself.
  The deterministic writer handles ASN / loopback / platform / CLI.
* You do NOT pass ASN / loopback / CLI to the writer.  Only pass
  the prose plan with the Summary block.  Facts come from the DB.
* You do NOT construct nested implementation_json / rollback_json /
  post_check_json strings.  Those don't exist here.
* If the writer returns `status=error` with `blockers`, surface
  them to the user.  Do NOT retry with fabricated "fix" arguments.

## Supported intents (in `render_tcf`)

| intent_type    | Description |
|----------------|---|
| `ebgp_direct`  | Direct eBGP session between 2 devices, different ASNs |

For other intents, write the prose plan but skip step 5 — escalate
to a human operator (`render_tcf` will return an "unsupported intent"
error if you try anyway).

## Sandbox SQL rule (inherited from analyze)

`sim.execute()` with literal SQL starting with `CREATE` / `INSERT` etc.
MUST use a variable (sandbox_guard pattern):

```python
_sql = "CREATE TABLE sim_x (col VARCHAR)"
sim.execute(_sql)  # NOT: sim.execute("CREATE TABLE ...")
```
