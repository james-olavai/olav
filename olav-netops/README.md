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

### Docker

The platform repo ships a compose profile that builds this package in and
starts Batfish alongside it:

```bash
docker compose --profile netops up -d batfish                        # wait for healthy
docker compose --profile netops run --rm olav-netops agent install olav-netops
docker compose --profile netops run --rm olav-netops doctor
docker compose --profile netops run --rm olav-netops --agent netops "/netops_init"
```

`run`, not `up`, for the agent itself — Batfish is the only long-running service
here. Device credentials come from `CLAB_USERNAME` / `CLAB_PASSWORD`; mount a key
directory with `SSH_KEY_DIR` for key-based access.

Containerlab is **not** run inside the container: it needs the host's network
namespace and Docker socket. Run it on the host and let the netops agent reach
the resulting devices over the network.

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
