# Installation

This page walks you through installing and initializing OLAV in 5 minutes.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-01 | `olav version` reports version correctly | ✅ v0.10.0 |
    | C-L2-13 | `olav init` creates project directory structure | ✅ v0.10.0 |

---

## Prerequisites

| Dependency | Description |
|-----------|-------------|
| Python 3.11+ | Runtime environment for OLAV |
| [`uv`](https://docs.astral.sh/uv/) | Recommended Python package manager, 10-100x faster than pip |
| LLM API Key | Supports OpenAI, Anthropic, Ollama (local), and more |

## Step 1: Download and Install

```bash
git clone https://github.com/olav-ai/olav.git
cd olav
uv sync
```

Verify the installation:

```bash
uv run olav version
```

Expected output:
```
Version:   v0.10.0
```

## Step 2: Initialize a Project

Navigate to your working directory (typically where you manage infrastructure) and run:

```bash
olav init
```

OLAV creates a `.olav/` directory with all required configuration and data:

```
.olav/
├── config/
│   ├── api.json        ← LLM + auth config (contains keys — do not commit)
│   ├── services.yaml   ← registered external services
│   └── settings.json   ← platform settings (active Agent, etc.)
├── databases/
│   ├── audit.duckdb    ← audit log (auto-records all operations)
│   └── domain.duckdb   ← domain data (devices, parsed outputs, etc.)
└── workspace/
    └── core/           ← pre-deployed core Agent
        ├── AGENT.md    ← Agent capability definition
        └── MANIFEST.yaml ← route keywords and version info
```

## Step 3: Configure LLM

Edit `.olav/config/api.json` with your LLM API key:

=== "OpenAI"
    ```json
    {
      "llm": {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "sk-..."
      }
    }
    ```
=== "Anthropic"
    ```json
    {
      "llm": {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "api_key": "sk-ant-..."
      }
    }
    ```
=== "OpenRouter (multi-model)"
    ```json
    {
      "llm": {
        "provider": "custom",
        "model": "openai/gpt-4o",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-..."
      }
    }
    ```
=== "Ollama (local/offline)"
    ```json
    {
      "llm": {
        "provider": "ollama",
        "model": "llama3.1",
        "base_url": "http://localhost:11434"
      }
    }
    ```

!!! warning "Protect your keys"
    `api.json` contains API keys. **Always** add `.olav/config/` to `.gitignore`.

## Step 4: Set Up .gitignore

The workspace is safe to commit — share Agent definitions with your team. Config and databases should not be committed:

```gitignore
# .gitignore
.olav/config/      # contains API keys
.olav/databases/   # contains audit logs and domain data
.olav/run/         # runtime PID files
```

```bash
git add .olav/workspace/
git commit -m "feat: init olav workspace"
```

---

!!! tip "Environment variable configuration"
    If you prefer not to store keys in files, configure via environment variables:
    ```bash
    export OLAV_LLM_API_KEY="sk-..."
    export OLAV_LLM_MODEL="gpt-4o"
    ```
    See [Configuration Reference →](../reference/configuration.md)

**Next:** [Your First Query →](first-query.md)
