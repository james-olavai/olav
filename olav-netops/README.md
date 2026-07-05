# olav-netops 🐺

Network-operations domain extension for the [OLAV](https://pypi.org/project/olav/)
agentic operations platform: SSH collection (Nornir + TextFSM), topology
analysis and What-If simulation (networkx), cross-snapshot drift detection,
compliance audits, and ContainerLab digital-twin validation.

## Install

```bash
pip install olav olav-netops
olav skill install olav-netops     # deploys the netops + audit agents
```

The second command deploys the agent workspaces bundled inside this wheel
into your project's `.olav/workspace/`. From then on:

```bash
olav --agent netops "/netops_init"                 # collect device data via SSH
olav --agent netops "simulate R2 link failure"     # What-If analysis
olav --agent audit  "run bgp_health check"         # compliance profiles
```

With Batfish simulation support:

```bash
pip install "olav-netops[sim]"
```

## What it adds

| Agent | Capabilities |
|-------|--------------|
| `netops` | Parallel SSH collection (command-whitelisted), BGP/OSPF analysis, topology queries, ECMP/failure simulation, ContainerLab twin deploy + commit-validate |
| `audit` | Health-check profiles (author + run), schema-aware reporting, TextFSM template learning |

Plus `netops.*` DuckDB tables auto-registered into the platform's ingest
pipeline, and slash commands (`/netops_init`, `/netops_snapshot`) exposed
through the platform CLI/TUI.

## Documentation

**Docs**: [docs.olavai.com](https://docs.olavai.com/netops/quick-start/) ·
**Website**: [olavai.com](https://olavai.com)

## Versioning

`olav-netops` releases in lockstep with the `olav` platform — install
matching versions (the dependency pin enforces the minimum).

## License

BSL-1.1 — Business Source License 1.1 (same as the OLAV platform).
