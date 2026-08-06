# Running OLAV in Docker

Two shapes, selected by compose profile:

| | Image | Contains |
|---|---|---|
| Platform only | `olav:local` | CLI, runtime, platform agents — 5 agents / 10 sub-agents / 9 tools |
| Platform + network domain | `olav-netops:local` | the above plus olav-netops and Batfish — 6 / 17 / 19 |

## `run`, not `up`

OLAV is an interactive terminal application, not a server. There is nothing to
daemonise: `docker compose up olav` starts a container that immediately exits.
Every OLAV invocation is a `run`:

```bash
docker compose run --rm olav doctor
docker compose run --rm olav --agent core "how many devices are there?"
```

The only long-running service is Batfish, which is the only thing you `up`.

## First run

```bash
cp .env.docker.example .env          # then fill in the endpoint + key
docker compose build olav
docker compose run --rm olav init    # scaffolds /data/.olav
docker compose run --rm olav doctor  # 11 checks, zero LLM calls
```

`doctor` is the fastest way to find a misconfiguration; it makes no model calls,
so it answers in a second and never fails for endpoint reasons. On a fresh
install with no key it reports 8/11 — `llm`, `embedding` and `memory` are red
because nothing is configured yet, not because anything is broken.

## Adding the network domain

```bash
docker compose --profile netops build olav-netops
docker compose --profile netops up -d batfish            # wait for healthy
docker compose --profile netops run --rm olav-netops agent install olav-netops
docker compose --profile netops run --rm olav-netops doctor
```

`agent install` prints `workspace 'audit' is platform-owned and already exists;
skipping overwrite`. That is correct, not a warning to fix: the platform image
already ships the audit workspace, and overwriting it with a sub-repo's dev
mirror is how the two drift apart.

Batfish takes about a minute to accept connections. The healthcheck probes port
9996 — the one netops actually uses — with a 60s `start_period`, so
`depends_on: service_healthy` does not fail a cold start.

## What persists

One named volume, `olav-data`, mounted at `/data`. Everything OLAV keeps lives
under it:

```
/data/.olav/config/api.json     model, provider, endpoint (written by `init`)
/data/.olav/databases/          DuckDB (network + audit) and LanceDB (memory)
/data/.olav/workspace/          agents, deployed by `init` / `agent install`
/data/exports/                  reports, diagrams, change plans, query CSVs
```

`docker compose down` keeps it; `down -v` deletes it. To work on the exports
from your host instead, replace the volume with a bind mount:

```yaml
    volumes:
      - ./olav-data:/data
```

The image runs as uid 1000, so a bind-mounted directory needs to be writable by
that uid.

## Configuration

`.env` carries only what does not belong in a config file — keys, credentials,
tier. The model, provider and endpoint go in `.olav/config/api.json`, which
`init` writes interactively.

Two settings are worth understanding rather than copying:

**`OLAV_LLM_MODEL_TIER`** (`small` ≈8K / `medium` ≈32K / `large` ≥200K usable
context) drives recall `top_k` and the `execute_sql` row cap. Over-stating it
does not fail immediately — it quietly overruns the served window on a long run,
which surfaces as `agent error, code 400`. `doctor` compares the budget against
the window the server advertises and flags the mismatch before you hit it.

**`OLAV_EMBEDDING_MODE`** defaults to `api`. `local` runs sentence-transformers
in process and needs the `[local-embed]` extra, which this image does not install
— it pulls a CUDA runtime for a wheel most deployments do not want. If your
embedding server rejects long inputs with HTTP 500 rather than truncating them
(a 512-token ubatch does this past roughly 1000 characters), set
`OLAV_EMBED_MAX_CHARS` — and raise it only together with the server's batch
size, never on its own.

## Reaching an endpoint on the host

`host.docker.internal` is mapped to the host gateway in both services, so an LLM
served on the machine running Docker is reachable there:

```
OLAV_EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
```

An endpoint elsewhere on the network needs no special handling.

## Device access (netops profile)

`CLAB_USERNAME` / `CLAB_PASSWORD` are the credentials netops uses to reach lab
and production devices over SSH — the same names the rest of the system uses.
For key-based access, point `SSH_KEY_DIR` at a directory holding the key; it is
mounted read-only at `/home/olav/.ssh`.

Containerlab is **not** run from inside this container. It needs privileged
access to the host's network namespace and Docker socket, and granting a
container that is a larger decision than a compose default should make. Run
`containerlab` on the host and let the netops agent reach the resulting devices
over the network.

## Known limits

- **No web UI.** It moved to olav-ent, so there is no HTTP port to publish. The
  interface is the terminal.
- **`local` embedding is unavailable** in this image by design (see above).
- **Containerlab is out of scope** (see above).
- **The image is not published.** Both targets build from this repo;
  `docker compose build` is the only way to obtain them today.
