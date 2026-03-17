# OLAV Quick Start

This guide reflects the current v0.11 code path.

The shortest path to a working local setup is:

1. Initialize the platform workspace with `olav init`.
2. Create an admin user and save the returned token to `~/.olav/token`.
3. Run a query from the CLI.
4. If you need network inventory collection, install and run the optional netops bootstrap.

## 1. Prerequisites

From the repository root:

```bash
uv sync
uv run olav version
```

If you are running directly from source, prefer `uv run olav ...` in the examples below. If OLAV is already installed as a CLI, you can replace `uv run olav` with `olav`.

## 2. Initialize The Platform

Create the baseline platform directories and default config:

```bash
uv run olav init
```

Current `init` creates:

```text
.olav/config/
.olav/workspace/
.olav/databases/
.olav/logs/
exports/snapshots/json/
exports/snapshots/raw/
```

It also creates `.olav/config/api.json` if that file does not already exist.

## 3. Configure The LLM

Edit `.olav/config/api.json` and add your provider credentials.

Example:

```json
{
  "llm": {
    "provider": "openai",
    "model": "gpt-4-turbo",
    "api_key": "your-openai-api-key"
  },
  "embedding": {
    "mode": "local"
  }
}
```

At this stage the platform is usable even without the netops extension.

## 4. Create The First Admin User

The current implementation does not yet rely on a guided `olav onboard` bootstrap flow for user creation. The implemented path is the admin user command.

Create the first admin user:

```bash
uv run olav admin "add-user admin --role admin"
```

The command returns a token once. Save it immediately:

```bash
mkdir -p ~/.olav
printf '%s\n' 'PASTE_TOKEN_HERE' > ~/.olav/token
chmod 600 ~/.olav/token
```

List current users:

```bash
uv run olav admin "list-users"
```

Create another user:

```bash
uv run olav admin "add-user alice --role user"
```

Note: the current CLI admin dispatcher expects the admin action as a single quoted argument.

## 5. Run Your First Query

Interactive mode:

```bash
uv run olav
```

Single-query mode:

```bash
uv run olav "How many devices are online?"
uv run olav --agent ops "Check network status"
uv run olav --agent audit "Summarize recent audit findings"
```

The natural-language query is passed directly to the CLI. You do not need a `query` subcommand.

## 6. Optional: Bootstrap NetOps Collection

Network collection is currently an extension-style capability, not part of the minimal platform bootstrap.

Install the netops package from this repository:

```bash
uv pip install -e olav-netops
```

Then run the netops bootstrap in dry-run mode first:

```bash
python olav-netops/scripts/netops_init.py --dry-run
```

Then run the full bootstrap:

```bash
python olav-netops/scripts/netops_init.py
```

What that bootstrap is intended to do:

1. Check infrastructure and LLM connectivity.
2. Run inventory and collection setup.
3. Parse collected outputs.
4. Generate topology artifacts.
5. Register the `trace_learner` cron task.

For the current NetOps bootstrap and troubleshooting path, see `../netops/06_QUICK_START.md`.

## 7. Common First Commands

```bash
uv run olav help
uv run olav list
uv run olav version
uv run olav admin status
uv run olav workspace status
```

## 8. Developer Entry: Add An Extension

If you are extending the platform rather than just using it, the shortest current path is:

1. Create or prepare a source directory with `MANIFEST.yaml`.
2. Add `SKILL.md` or `AGENT.md` plus the runtime implementation.
3. Install it into `.olav/workspace/` through the workspace control plane.
4. Validate it before first use.

Typical commands:

```bash
uv run olav workspace install ./path/to/extension
uv run olav workspace validate <name>
uv run olav workspace status
```

If the capability is a built-in platform skill instead of a package-managed extension, the current model is different:

1. Add the skill under the target agent directory in `.olav/workspace/`.
2. Add its `SKILL.md`.
3. Add its tool implementation.
4. Declare it explicitly in that agent's `AGENT.md`.

See `07_API_OPENAPI.md`, `08_AGENT_SKILL_REGISTRATION.md`, and `09_EXTENSION_LIFECYCLE.md` before changing platform control-plane files.

## 9. Troubleshooting

### `olav init` succeeds but queries cannot use the LLM

Check `.olav/config/api.json` first. The current `init` command only writes a baseline config. It does not provision secrets for you.

### Admin user created but authentication still falls back to OS identity

Make sure the token is stored in `~/.olav/token` and that file permissions are `600`.

### You expected `olav onboard`

Some older docs still describe a planned bootstrap-token onboarding flow. The implemented path in the current codebase is:

1. `olav init`
2. `olav admin "add-user ..."`
3. save token to `~/.olav/token`

## 10. Next Reading

- [docs/03_CORE_CONCEPTS.md](./03_CORE_CONCEPTS.md)
- [docs/06_AAA.md](./06_AAA.md)
- [docs/07_API_OPENAPI.md](./07_API_OPENAPI.md)
- [docs/08_AGENT_SKILL_REGISTRATION.md](./08_AGENT_SKILL_REGISTRATION.md)
- [docs/09_EXTENSION_LIFECYCLE.md](./09_EXTENSION_LIFECYCLE.md)
- [docs/06_QUICK_START.md](../netops/06_QUICK_START.md)