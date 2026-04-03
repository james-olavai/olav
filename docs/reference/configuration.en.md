# Configuration Reference

All configuration is centralized in the `.olav/config/api.json` file. Running `olav init` creates a baseline version.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-38 | `agent_overrides` assigns different LLM models to different Agents | ✅ v0.10.0 |
    | C-L2-39 | `OLAV_LLM_*` environment variables override config file | ✅ v0.10.0 |

!!! warning "Protect your config file"
    `api.json` contains API keys — do not commit it to Git. Add `.olav/config/` to your `.gitignore`.

---

## File Structure

```json
{
  "llm": { ... },
  "embedding": { ... },
  "auth": { ... },
  "agent_overrides": { ... }
}
```

---

## LLM Configuration

OLAV supports multiple LLM providers. Select the one you use:

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
    Anthropic models automatically enable Prompt Caching to reduce the cost of repeated requests.

=== "OpenRouter (Multi-Model Aggregator)"
    ```json
    {
      "llm": {
        "provider": "custom",
        "model": "x-ai/grok-2",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-..."
      }
    }
    ```
    OpenRouter gives you access to virtually all mainstream models.

=== "Ollama (Local / Offline)"
    ```json
    {
      "llm": {
        "provider": "ollama",
        "model": "llama3.1",
        "base_url": "http://localhost:11434"
      }
    }
    ```
    No API key required — data never leaves your machine.

### LLM Field Reference

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `provider` | ✅ | | Provider: `openai` / `anthropic` / `azure_openai` / `ollama` / `groq` / `mistral` / `custom` |
| `model` | ✅ | | Model ID (e.g., `gpt-4o`, `claude-3-5-sonnet-20241022`) |
| `api_key` | ✅* | | API key (not required for Ollama) |
| `base_url` | | | Required for `custom` provider; optional for others (use for self-hosted proxies) |
| `temperature` | | `0.1` | Generation temperature — lower values produce more deterministic output |
| `max_tokens` | | `32000` | Maximum number of tokens to generate |

---

## Embedding Configuration

The knowledge base and Agent memory use vector embeddings for semantic search.

=== "API Mode (Recommended)"
    ```json
    "embedding": {
      "mode": "api",
      "api": {
        "model": "openai/text-embedding-3-small",
        "base_url": "https://openrouter.ai/api/v1"
      },
      "fallback": { "enabled": true }
    }
    ```
    When `fallback` is enabled, the system automatically falls back to a local model if the API is unavailable.

=== "Local Mode (Offline / Air-Gapped)"
    ```json
    "embedding": {
      "mode": "local"
    }
    ```
    Uses the BAAI/bge model — CPU only, no network connection required.

---

## Authentication Mode

Configured in the `auth` section to determine how user identity is established:

| Mode | Use Case | Description |
|------|----------|-------------|
| `none` | Personal use, local development | Default — uses the OS username |
| `token` | Small teams | Built-in OLAV token authentication |
| `ldap` | Enterprise | Connects to an LDAP directory |
| `ad` | Enterprise | Connects to Active Directory |
| `oidc` | SSO | Connects to OpenID Connect |

---

## Assigning Different Models to Different Agents

You can use different LLM models for specific Agents — for example, a cheap small model for quick queries and a powerful large model for complex analysis:

```json
"agent_overrides": {
  "quick": { "model": "gpt-4o-mini" },
  "audit": { "provider": "anthropic", "model": "claude-3-5-sonnet-20241022" }
}
```

Agents not listed in `agent_overrides` use the top-level `llm` configuration.

---

## Environment Variables

All configuration can be overridden via environment variables, which take precedence over `api.json`:

| Environment Variable | Config Equivalent | Description |
|---------------------|-------------------|-------------|
| `OLAV_LLM_MODEL` | `llm.model` | Model ID |
| `OLAV_LLM_API_KEY` | `llm.api_key` | API key |
| `OLAV_LLM_BASE_URL` | `llm.base_url` | API endpoint |
| `OPENAI_API_KEY` | `llm.api_key` | OpenAI shortcut |
| `ANTHROPIC_API_KEY` | `llm.api_key` | Anthropic shortcut |
| `OLAV_WEB_PORT` | | Web service port |
| `OLAV_WEB_HOST` | | Web service bind address |

!!! tip "Use environment variables in CI/CD"
    In CI/CD pipelines, pass secrets via environment variables rather than files to avoid writing them to disk.

---

## Remote AsyncSubAgents

OLAV can connect to remote LangGraph Cloud or self-hosted LangGraph deployments as AsyncSubAgents. Add an `async_subagents` array to `api.json`:

```json
{
    "async_subagents": [
        {
            "name": "remote-ops",
            "description": "High-capacity ops agent running on LangGraph Cloud",
            "url": "https://my-deployment.langsmith.com",
            "assistant_id": "ops",
            "api_key_env": "LANGGRAPH_API_KEY"
        }
    ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | ✅ | Unique subagent name (used by `olav_delegate` tool) |
| `description` | ✅ | Human-readable description for orchestrator routing |
| `url` | ✅ | LangGraph deployment base URL |
| `assistant_id` | ✅ | Graph/assistant ID on the remote deployment |
| `api_key_env` | ❌ | Env var name holding the API key. Falls back to `LANGGRAPH_API_KEY` |

Remote subagents are loaded at startup alongside local workspace subagents. Failures are skipped gracefully — they never block local agent initialization.

---

## Hook System

Configure external commands triggered by OLAV session events in `~/.olav/hooks.json`:

```json
{
    "hooks": [
        { "event": "session.start", "command": "notify-send 'OLAV session started'" },
        { "event": "tool.call",     "command": "logger -t olav 'Tool: $OLAV_HOOK_TOOL'" }
    ]
}
```

See [Agent Harness → Event Hook System](../concepts/agent-harness.md#event-hook-system) for the full event reference.
