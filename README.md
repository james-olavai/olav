# OLAV

OLAV is the core platform for AI-assisted operational workflows.

This repository currently contains two layers:

1. `src/olav/`: the OLAV core platform.
2. `olav-netops/`: the optional NetOps extension package.

The CLI accepts natural-language requests directly. Network-specific collection and bootstrap flows live in the NetOps extension, not in the minimal platform bootstrap.

## Platform Quick Start

From the repository root:

```bash
uv sync
uv run olav init
uv run olav admin "add-user admin --role admin"
```

Save the returned token to `~/.olav/token` before using authenticated workflows.

Examples:

```bash
uv run olav
uv run olav "How many devices are in the database?"
uv run olav --agent ops "Check network status"
uv run olav --agent audit "Summarize recent findings"
```

## NetOps Extension

Install the optional NetOps package when you need device collection, topology generation, and network bootstrap workflows:

```bash
uv pip install -e olav-netops
python olav-netops/scripts/netops_init.py --dry-run
python olav-netops/scripts/netops_init.py
```

## Documentation

The authoritative docs are split by domain:

- [Documentation Hub](docs/01_README.md)
- [OLAV Platform Docs](docs/olav/01_README.md)
- [NetOps Docs](docs/netops/01_README.md)
- [中文文档总导航](docs/cn/01_README.md)

## Notes

- Platform user management is handled through `olav admin`.
- The current built-in roles are `admin`, `user`, and `readonly`.
- `olav-netops` is an optional package; the root `olav` package does not vendor NetOps runtime dependencies by default.

## License

MIT
