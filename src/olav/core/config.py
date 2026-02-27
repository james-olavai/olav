"""
OLAV Configuration System v2.0

Unified API config for LLM and Embedding.
"""

import json
import os
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / ".olav" / "config"
_AGENT_DIR = os.getenv("AGENT_DIR", ".olav")
_AGENT_DIR_PATH = _PROJECT_ROOT / _AGENT_DIR


class ConfigLoader:
    _instance = None
    _loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not ConfigLoader._loaded:
            self._load_all()
            ConfigLoader._loaded = True

    def _load_json(self, filename: str) -> dict:
        path = _CONFIG_DIR / filename
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse {filename}: {e}")
        return {}

    def _load_all(self):
        # Unified API config
        self._api = self._load_json("api.json")

        if self._api:
            self._llm = self._api.get("llm", {})
            self._embedding = self._api.get("embedding", {})
            self._shared = self._api.get("shared", {})
        else:
            self._llm = self._load_json("llm.json")
            self._embedding = self._load_json("embedding.json")
            self._shared = {}

        self._paths = self._load_json("paths.json")
        self._runtime = self._load_json("runtime.json")
        self._tasks = self._load_json("tasks.json")

    def _env_override(self, section: str, key: str, default: Any) -> Any:
        env_key = f"OLAV_{section.upper()}_{key.upper()}"
        value = os.getenv(env_key)
        if value is not None:
            if isinstance(default, bool):
                return value.lower() in ("true", "1", "yes")
            elif isinstance(default, int):
                try:
                    return int(value)
                except ValueError:
                    return default
            elif isinstance(default, float):
                try:
                    return float(value)
                except ValueError:
                    return default
            return value
        return default

    @property
    def llm(self):
        return LLMConfig(self._llm, self)

    @property
    def embedding(self):
        return EmbeddingConfig(self._embedding, self)

    @property
    def paths(self):
        return PathsConfig(self._paths, self)

    @property
    def runtime(self):
        return RuntimeConfig(self._runtime, self)

    @property
    def tasks(self):
        return self._tasks


class LLMConfig:
    def __init__(self, data: dict, loader: ConfigLoader):
        self._data = data
        self._loader = loader

    @property
    def provider(self) -> str:
        return self._loader._env_override("llm", "provider", self._data.get("provider", "openai"))

    @property
    def api_key(self) -> str:
        shared = getattr(self._loader, "_shared", {})
        key = shared.get("api_key", "")
        if not key:
            key = self._loader._env_override("llm", "api_key", self._data.get("api_key", ""))
        if not key:
            key = os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or ""
        return key

    @property
    def model(self) -> str:
        return self._loader._env_override("llm", "model", self._data.get("model", "gpt-4-turbo"))

    @property
    def temperature(self) -> float:
        return self._loader._env_override("llm", "temperature", self._data.get("temperature", 0.1))

    @property
    def max_tokens(self) -> int:
        return self._loader._env_override("llm", "max_tokens", self._data.get("max_tokens", 16000))

    @property
    def base_url(self) -> str:
        return self._loader._env_override("llm", "base_url", self._data.get("base_url", ""))

    @property
    def custom_headers(self) -> dict:
        return self._data.get("custom_headers", {})


class EmbeddingConfig:
    def __init__(self, data: dict, loader: ConfigLoader):
        self._data = data
        self._loader = loader

    @property
    def mode(self) -> str:
        return self._loader._env_override("embedding", "mode", self._data.get("mode", "local"))

    @property
    def local_model(self) -> str:
        local = self._data.get("local", {})
        return self._loader._env_override(
            "embedding", "model", local.get("model", "BAAI/bge-small-zh-v1.5")
        )

    @property
    def device(self) -> str:
        local = self._data.get("local", {})
        return local.get("device", "cpu")

    @property
    def normalize_embeddings(self) -> bool:
        local = self._data.get("local", {})
        return local.get("normalize_embeddings", True)

    @property
    def openai_api_key(self) -> str:
        shared = getattr(self._loader, "_shared", {})
        key = shared.get("api_key", "")
        if not key:
            api = self._data.get("api", {})
            key = self._loader._env_override("embedding", "api_key", api.get("api_key", ""))
        if not key:
            key = os.getenv("OPENAI_API_KEY") or ""
        return key

    @property
    def openai_model(self) -> str:
        api = self._data.get("api", {})
        return self._loader._env_override(
            "embedding", "model", api.get("model", "text-embedding-3-small")
        )

    @property
    def openai_base_url(self) -> str:
        api = self._data.get("api", {})
        return self._loader._env_override("embedding", "base_url", api.get("base_url", ""))

    @property
    def fallback_enabled(self) -> bool:
        fallback = self._data.get("fallback", {})
        return self._loader._env_override(
            "embedding", "fallback_enabled", fallback.get("enabled", True)
        )

    @property
    def api_key(self) -> str:
        return self.openai_api_key

    @property
    def api_model(self) -> str:
        return self.openai_model


class PathsConfig:
    def __init__(self, data: dict, loader: ConfigLoader):
        self._data = data
        self._loader = loader

    @property
    def agent_dir(self) -> str:
        return self._loader._env_override(
            "paths", "agent_dir", self._data.get("agent_dir", ".olav")
        )

    @property
    def databases_dir(self) -> str:
        return self._loader._env_override(
            "paths", "databases_dir", self._data.get("databases_dir", ".olav/databases")
        )

    @property
    def exports_dir(self) -> str:
        return self._data.get("exports_dir", "exports")

    @property
    def reports_dir(self) -> str:
        return self._data.get("reports_dir", "exports/reports")

    @property
    def logs_dir(self) -> str:
        return self._data.get("logs_dir", ".olav/logs")

    @property
    def skills_dir(self) -> str:
        # Legacy property, unified with workspace_dir
        return self.workspace_dir

    @property
    def knowledge_dir(self) -> str:
        return self._loader._env_override(
            "paths", "knowledge_dir", self._data.get("knowledge_dir", ".olav/knowledge")
        )

    @property
    def workspace_dir(self) -> str:
        return self._loader._env_override(
            "paths", "workspace_dir", self._data.get("workspace_dir", ".olav/workspace")
        )

    @property
    def templates_dir(self) -> str:
        return self._data.get("templates_dir", ".olav/templates")

    @property
    def config_dir(self) -> str:
        return self._data.get("config_dir", ".olav/config")

    @property
    def main_db(self) -> str:
        files = self._data.get("files", {})
        return files.get("main_db", ".olav/databases/main.duckdb")

    @property
    def llm_cache(self) -> str:
        files = self._data.get("files", {})
        return files.get("llm_cache", ".olav/databases/llm_cache.sqlite")

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

    @property
    def agent_dir_path(self) -> Path:
        return _AGENT_DIR_PATH


class RuntimeConfig:
    def __init__(self, data: dict, loader: ConfigLoader):
        self._data = data
        self._loader = loader

    @property
    def use_textfsm(self) -> bool:
        exec_data = self._data.get("execution", {})
        return self._loader._env_override(
            "runtime", "use_textfsm", exec_data.get("use_textfsm", True)
        )

    @property
    def log_level(self) -> str:
        log_data = self._data.get("logging", {})
        return self._loader._env_override("runtime", "log_level", log_data.get("level", "INFO"))


_config = None


def get_config() -> ConfigLoader:
    global _config
    if _config is None:
        _config = ConfigLoader()
    return _config


def reload_config():
    global _config
    ConfigLoader._loaded = False
    ConfigLoader._instance = None
    _config = ConfigLoader()
    return _config


def get_llm_config() -> LLMConfig:
    return get_config().llm


def get_embedding_config() -> EmbeddingConfig:
    return get_config().embedding


def get_paths_config() -> PathsConfig:
    return get_config().paths


def get_runtime_config() -> RuntimeConfig:
    return get_config().runtime


# Backward compatibility
class SettingsCompat:
    """Backward compatibility properties."""
    @property
    def llm_provider(self) -> str:
        return get_llm_config().provider

    @property
    def llm_model_name(self) -> str:
        return get_llm_config().model

    @property
    def llm_temperature(self) -> float:
        return get_llm_config().temperature

    @property
    def llm_api_key(self) -> str:
        return get_llm_config().api_key

    @property
    def llm_base_url(self) -> str:
        return get_llm_config().base_url

    @property
    def llm_max_tokens(self) -> int:
        return get_llm_config().max_tokens

    @property
    def embedding_mode(self) -> str:
        return get_embedding_config().mode

    @property
    def embedding_local_model(self) -> str:
        return get_embedding_config().local_model

    @property
    def embedding_enable_fallback(self) -> bool:
        return get_embedding_config().fallback_enabled

    @property
    def embedding_model(self) -> str:
        return get_embedding_config().openai_model



# Simple settings class for backward compatibility
class Settings(SettingsCompat):
    pass

_settings_instance = Settings()

def get_settings():
    return _settings_instance

settings = _settings_instance

# --------------------------------------------------------------------------
# Path constants for tool compatibility - map from config properties
# --------------------------------------------------------------------------


class _PathResolver:
    """Resolve paths from config with caching."""
    _cache: dict = {}

    def resolve(self, key: str) -> Path:
        if key not in self._cache:
            config = get_paths_config()
            # Map config property names to constant names
            prop_map = {
                "main_db": "MAIN_DB_PATH",
                "databases_dir": "DATABASES_DIR",
                "exports_dir": "EXPORTS_DIR",
                "reports_dir": "REPORTS_DIR",
                "logs_dir": "LOGS_DIR",
                "knowledge_dir": "KNOWLEDGE_BASE_DIR",
                "workspace_dir": "WORKSPACE_DIR",
                "templates_dir": "TEXTFSM_TEMPLATES_DIR",
                "config_dir": "CONFIG_DIR",
                "skills_dir": "SKILLS_DIR",
                "agent_dir": "AGENT_DIR",
            }
            prop = prop_map.get(key, key)
            if hasattr(config, prop.lower()):
                val = getattr(config, prop.lower())
                self._cache[key] = _PROJECT_ROOT / val if val else _PROJECT_ROOT
            else:
                self._cache[key] = _PROJECT_ROOT
        return self._cache[key]


_path_resolver = _PathResolver()

# Module-level path constants for backward compatibility
MAIN_DB_PATH = _path_resolver.resolve("main_db")
DATABASES_DIR = _path_resolver.resolve("databases_dir")
EXPORTS_DIR = _path_resolver.resolve("exports_dir")
REPORTS_DIR = _path_resolver.resolve("reports_dir")
LOGS_DIR = _path_resolver.resolve("logs_dir")
KNOWLEDGE_BASE_DIR = _path_resolver.resolve("knowledge_dir")
WORKSPACE_DIR = _path_resolver.resolve("workspace_dir")
TEXTFSM_TEMPLATES_DIR = _path_resolver.resolve("templates_dir")
CONFIG_DIR = _path_resolver.resolve("config_dir")
SKILLS_DIR = WORKSPACE_DIR
AGENT_DIR = _path_resolver.resolve("agent_dir")
SKILL_BASE_PATH = WORKSPACE_DIR
NETWORK_DB_PATH = MAIN_DB_PATH  # Legacy alias
UNIFIED_DB = MAIN_DB_PATH  # Legacy alias
SNAPSHOTS_DIR = EXPORTS_DIR / "snapshots"
SYNC_DIR = EXPORTS_DIR / "sync"

# User-local paths (from old config.paths)
import os
try:
    _username = os.environ.get("USER") or os.getlogin()
except Exception:
    _username = os.environ.get("USERNAME", "default_user")

USER_HISTORY_DIR = Path.home() / ".olav" / "history"
USER_HISTORY_PATH = USER_HISTORY_DIR / f"{_username}.txt"
USER_SESSION_DIR = Path.home() / ".olav" / "sessions"
GUARD_WHITELIST_PATH = SKILLS_DIR / "guard" / "whitelist.yaml"
CACHE_DIR = AGENT_DIR / "cache"


__all__ = [
    "settings", "Settings", "get_settings",
    "MAIN_DB_PATH", "DATABASES_DIR", "EXPORTS_DIR", "REPORTS_DIR",
    "LOGS_DIR", "KNOWLEDGE_BASE_DIR", "WORKSPACE_DIR", "TEXTFSM_TEMPLATES_DIR",
    "CONFIG_DIR", "SKILLS_DIR", "AGENT_DIR", "SKILL_BASE_PATH",
    "NETWORK_DB_PATH", "UNIFIED_DB", "SNAPSHOTS_DIR", "SYNC_DIR",
    "USER_HISTORY_PATH", "USER_HISTORY_DIR", "USER_SESSION_DIR", "GUARD_WHITELIST_PATH",
    "get_config", "get_llm_config", "get_embedding_config", "get_paths_config", "get_runtime_config",
]

