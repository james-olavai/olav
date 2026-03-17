# NetOps Quick Start

This guide describes the current NetOps path in the codebase.

NetOps is an extension-style capability layered on top of the OLAV platform. It is not the minimal platform bootstrap itself.

## 1. Initialize The Platform First

From the repository root:

```bash
uv sync
uv run olav init
uv run olav admin "add-user admin --role admin"
```

Save the returned token to `~/.olav/token` and lock the permissions:

```bash
mkdir -p ~/.olav
printf '%s\n' 'PASTE_TOKEN_HERE' > ~/.olav/token
chmod 600 ~/.olav/token
```

Before any NetOps bootstrap, make sure `.olav/config/api.json` contains a working LLM configuration.

## 2. Install The NetOps Package

Install the local extension package from this repository:

```bash
uv pip install -e olav-netops
```

## 3. Run The NetOps Bootstrap

Dry-run first:

```bash
python olav-netops/scripts/netops_init.py --dry-run
```

Then run the real bootstrap:

```bash
python olav-netops/scripts/netops_init.py
```

The bootstrap script is responsible for:

1. Environment and infrastructure checks.
2. LLM connectivity verification.
3. Collection and parsing setup.
4. Topology generation.
5. `trace_learner` cron registration.

## 4. Query The Network

Use natural-language queries directly. The current CLI does not require a `query` subcommand.

```bash
uv run olav --agent ops "Show me the version of R1"
uv run olav --agent ops "What is the BGP status on all routers?"
uv run olav --agent ops "Draw the topology and show which devices are connected"
uv run olav --agent audit "Summarize current network health findings"
```

## 5. Operational Notes

- CLI workflows do not require a separate web service.
- The NetOps bootstrap path is script-driven through `olav-netops/scripts/netops_init.py`.
- Daily `trace_learner` scheduling is written into `~/.olav/cron.tab` by the bootstrap script.

## 6. Troubleshooting

### Dry-run fails

Resolve the prerequisites reported by the dry-run before attempting a full bootstrap.

### The NetOps package is not importable

Reinstall the local package from the repository root:

```bash
uv pip install -e olav-netops
```

### You expected `olav onboard`

Some older docs still describe a previous onboarding flow. The current NetOps path is:

1. `olav init`
2. `olav admin "add-user ..."`
3. `uv pip install -e olav-netops`
4. `python olav-netops/scripts/netops_init.py`

## 7. Related Docs

- [01_README.md](./01_README.md)
- [02_QUICK_QUERY.md](./02_QUICK_QUERY.md)
- [03_NETWORK_OPS.md](./03_NETWORK_OPS.md)
- [04_NETWORK_AUDIT.md](./04_NETWORK_AUDIT.md)
- [../olav/02_QUICK_START.md](../olav/02_QUICK_START.md)
