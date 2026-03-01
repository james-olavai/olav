# OLAV LLM API & Factory Modernization Plan (v0.11.0)

## 1. Vision & Objective
To eliminate the redundant, hardcoded provider-switching logic in `LLMFactory` and transition to a **Native + Config-Driven** architecture using LangChain's `init_chat_model`. This ensures 100% compatibility with custom APIs (OpenRouter/Groq) while simplifying the codebase and enabling per-agent model configurations.

## 2. Core Architectural Shift

| Feature | Legacy Approach (Switch-Case) | Modern Approach (Native Dict Injection) |
| :--- | :--- | :--- |
| **Logic** | 350+ lines of `if-elif` branches. | ~20 lines using `init_chat_model(**config_dict)`. |
| **Provider Support**| Manual imports and instantiation. | Automatic discovery via LangChain. |
| **Custom Headers** | Hardcoded OpenRouter logic. | Transparently loaded from `api.json`. |
| **Granularity** | Single global model. | **Per-Agent Model Mapping** support. |

---

## 3. Refactoring Roadmap (TDD)

### Phase 1: Config Schema Alignment
**Goal**: Ensure `.olav/config/api.json` keys match native LangChain/OpenAI parameter names.

- **Test (TDD)**: `tests/unit/test_llm_config_parsing.py`
  - Verify `settings.to_langchain_params()` returns a dict with `model`, `base_url`, and `default_headers`.
  - Verify `api_key` is correctly injected from `shared` or environment variables.
- **Action**: Update `src/olav/core/config.py` to provide a clean dictionary delivery method for LLM parameters.

### Phase 2: Factory Modernization (The "Purge")
**Goal**: Replace the massive `if-elif` block in `LLMFactory.get_chat_model`.

- **Test (TDD)**: `tests/unit/test_llm_factory_native.py`
  - Mock `init_chat_model`.
  - Assert that calling `LLMFactory.get_chat_model()` calls `init_chat_model` with the correct dictionary acquired in Phase 1.
- **Action**: 
  - Delete legacy provider branches (Ollama, Anthropic, etc.).
  - Implement `init_chat_model(**params)`.
  - Maintain the "OpenRouter Header Injection" as a dictionary-level enrichment if not present in the JSON.

### Phase 3: Multi-Agent Model Binding
**Goal**: Allow different agents (ops, config, audit) to use different LLM backends.

- **Test (TDD)**: `tests/unit/test_agent_model_binding.py`
  - Configure `ops` to use `groq` and `audit` to use `gpt-4o` in `api.json`.
  - Verify `OLAVAgent(agent_id="ops")` receives a Groq instance.
- **Action**: Update `ConfigLoader` to support an `agent_overrides` section in `api.json`.

### Phase 4: CLI Runtime Model Switching
**Goal**: Implement the `/model` slash command for instant switching.

- **Test (TDD)**: `tests/unit/test_cli_model_command.py`
  - Execute `/model gpt-4o`.
  - Verify that the next `_get_or_create_agent` call triggers a cache reset and uses the new model string.
- **Action**: Implement `cmd_model` in `src/olav/cli/commands/builtin.py`.

---

## 4. Implementation Guidelines (KISS & DRY)
- **No Hardcoding**: Do not hardcode provider names or model strings in `llm.py`.
- **Dependency Isolation**: Use `langchain.chat_models.init_chat_model` which handles dynamic imports of provider packages (no more manual `try-except` imports).
- **Error Handling**: Implement a fallback to the "default" model defined in `api.json` if a specific agent-override fails.
- **Redundancy Cleanup**: After migration, delete at least 250 lines from `src/olav/core/llm.py`.

## 5. Definition of Done
1. [ ] `LLMFactory.get_chat_model` is under 30 lines of code.
2. [ ] All custom APIs (OpenRouter/Groq) pass verification via `api.json` dict injection.
3. [ ] CLI `/model` command is functional.
4. [ ] All existing E2E tests pass without modification to the test logic.
