"""
OLAV Configuration System

Unified API config for LLM and Embedding.
"""

import json
import logging
import os
import re
import threading
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Sprint 0b model_tier: constitutional config for ARCH-16/17/18/19 ────────


class ModelTier(str, Enum):
    """OLAV model tier classifications.

    Downstream features (static_context depth, tool-return compaction,
    AutoRecall top_k, summarisation cadence, …) all key off this tier
    instead of carrying their own size heuristics.
    """

    SMALL = "small"    # ~4-8B class; usable context ~8K
    MEDIUM = "medium"  # ~13-34B class; usable context ~32K
    LARGE = "large"    # 70B+ / Claude / GPT-4; usable context ≥200K


# Per-tier feature defaults. Features that want different behaviour for
# small vs large models call ``tier_default(tier, key, fallback)``. Keep
# this dict inline — the issue tracker (ARCH-17/18/19) explicitly keys
# off it and a separate module would just add import-path churn.
TIER_DEFAULTS: dict[str, dict[str, Any]] = {
    "small": {
        "recall_top_k": 1,
        "return_compact_chars": 2000,
        "static_context_mode": "on_intent",
        "context_budget": 8000,      # ~4-8B class total window
        # ARCH-19 #A: on non-first turns, skip recall injection when fewer
        # than this fraction of the budget is still free. Small models run
        # tightest so skip sooner; large tier never skips.
        "recall_skip_headroom_pct": 0.20,
        # ARCH-16 (Round 41) — tool-level LIMITs:
        # rows from execute_sql surfaced to the LLM context (CSV still exports
        # full set at >50 rows regardless of tier).
        "execute_sql_context_rows": 10,
        # default `limit` for search_logs when caller omits it.
        "search_logs_default_limit": 20,
        # ARCH-19 SummarizationMiddleware tier threshold (Round 42):
        # fire summarization when conversation reaches this fraction of
        # ``context_budget``. Small tier summarizes early (50%) so the
        # model can keep chipping at tasks without blowing context;
        # large tier holds off (80%) because it has headroom and
        # summarization loses nuance.
        "summarization_trigger_pct": 0.50,
    },
    "medium": {
        "recall_top_k": 2,
        "return_compact_chars": 5000,
        "static_context_mode": "on_intent",
        "context_budget": 32000,
        "recall_skip_headroom_pct": 0.10,
        "execute_sql_context_rows": 20,
        "search_logs_default_limit": 50,
        "summarization_trigger_pct": 0.65,
    },
    "large": {
        "recall_top_k": 3,
        "return_compact_chars": 10000,
        "static_context_mode": "always",
        "context_budget": 200000,
        "recall_skip_headroom_pct": 0.00,
        "execute_sql_context_rows": 50,
        "search_logs_default_limit": 100,
        "summarization_trigger_pct": 0.80,
    },
}


def tier_default(tier: str, key: str, fallback: Any) -> Any:
    """Resolve a per-tier default or return ``fallback`` if unknown."""
    return TIER_DEFAULTS.get(tier, {}).get(key, fallback)


# Regex patterns for inferring tier from model name when the config
# doesn't set one explicitly. Order matters: check small-tier hints
# before medium (a "7b" in "qwen2-72b" would wrongly match "7b" alone,
# so the patterns use word boundaries).
_TIER_REGEX_SMALL = re.compile(r"\b(1\.?5b|3b|4b|7b|8b|gemma|phi-3|haiku-4-5)\b", re.I)
_TIER_REGEX_MEDIUM = re.compile(r"\b(13b|14b|22b|32b|34b|mixtral|mistral-small)\b", re.I)


def _resolve_project_root() -> Path:
    """Resolve the project root directory.

    When installed as a package, ``Path(__file__)`` points inside the venv's
    site-packages — not the user's working directory.  We prefer:
    1. ``OLAV_HOME`` env var (explicit override)
    2. The nearest ancestor of CWD that contains a ``.olav/`` directory
    3. CWD itself (fresh install — ``olav init`` will create ``.olav/`` here)
    """
    if home := os.getenv("OLAV_HOME"):
        return Path(home).resolve()
    cwd = Path.cwd()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / ".olav").is_dir():
            return candidate
    return cwd


_PROJECT_ROOT = _resolve_project_root()
_CONFIG_DIR = _PROJECT_ROOT / ".olav" / "config"
_AGENT_DIR = os.getenv("AGENT_DIR", ".olav")
_AGENT_DIR_PATH = _PROJECT_ROOT / _AGENT_DIR


_config_lock = threading.RLock()


class ConfigLoader:
    _instance = None
    _loaded = False

    def __new__(cls):
        if cls._instance is None:
            with _config_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not ConfigLoader._loaded:
            with _config_lock:
                if not ConfigLoader._loaded:
                    self._load_all()
                    ConfigLoader._loaded = True

    def _load_json(self, filename: str) -> dict:
        path = _CONFIG_DIR / filename
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse %s: %s", filename, e)
            except UnicodeDecodeError as e:
                logger.warning("Encoding error in %s (expected utf-8): %s", filename, e)
            except OSError as e:
                logger.warning("Cannot read %s: %s", filename, e)
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

        # Path configuration — all defaults are baked into PathsConfig properties.
        # Previously loaded from paths.json; now uses hardcoded defaults only so that
        # .olav/config/ stays minimal (platform-only files).
        self._paths: dict = {}
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
    def memory(self):
        return MemoryConfig(self._api.get("memory", {}), self)

    @property
    def auth(self):
        return AuthConfig(self._api.get("auth", {}), self)

    @property
    def dataset_export(self):
        return DatasetExportConfig(self._api.get("dataset_export", {}), self)

    @property
    def tasks(self):
        return self._tasks

    @property
    def security(self):
        return SecurityConfig(self._api.get("security", {}))


class SecurityConfig:
    """Parsed ``security`` section from api.json."""

    def __init__(self, data: dict):
        self._data = data

    @property
    def allowed_cidrs(self) -> list[str]:
        return list(self._data.get("allowed_cidrs") or [])

    @property
    def trust_proxy_headers(self) -> bool:
        return bool(self._data.get("trust_proxy_headers", False))


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
    def model_provider(self) -> str:
        return self._loader._env_override(
            "llm", "model_provider", self._data.get("model_provider", "")
        )

    @property
    def timeout(self) -> int:
        shared = getattr(self._loader, "_shared", {})
        return int(shared.get("timeout", self._data.get("timeout", 60)))

    @property
    def custom_headers(self) -> dict:
        return self._data.get("custom_headers", {})

    @property
    def model_tier(self) -> str:
        """Return ``"small"`` | ``"medium"`` | ``"large"`` (Sprint 0b).

        Resolution order:

        1. ``OLAV_LLM_MODEL_TIER`` env var.
        2. Explicit ``llm.model_tier`` in api.json / llm.json.
        3. Regex match on ``self.model`` (e.g. "gemma-7b" → small,
           "qwen2-32b" → medium).
        4. Conservative fallback ``"large"`` — downstream features that
           cap payloads will behave as if the caller has a large context.
        """
        explicit = self._loader._env_override(
            "llm", "model_tier", self._data.get("model_tier")
        )
        if explicit:
            return str(explicit).lower()
        name = (self.model or "").lower()
        if _TIER_REGEX_SMALL.search(name):
            return ModelTier.SMALL.value
        if _TIER_REGEX_MEDIUM.search(name):
            return ModelTier.MEDIUM.value
        return ModelTier.LARGE.value


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
    def audit_reports_dir(self) -> str:
        """Directory for audit inspection reports."""
        audit = self._data.get("audit", {})
        return audit.get("reports_dir", "exports/audit_reports")

    @property
    def audit_retention_days(self) -> int:
        """Number of days to retain audit records before archiving (GAP-5)."""
        audit = self._data.get("audit", {})
        return int(audit.get("retention_days", 90))

    @property
    def agent_outputs_dir(self) -> str:
        """Directory for agent output files (Mermaid diagrams, reports, etc.)."""
        return self._data.get("agent_outputs_dir", "exports/agent_outputs")

    @property
    def run_dir(self) -> str:
        return self._data.get("run_dir", "run")

    @property
    def logs_dir(self) -> str:
        return self._data.get("logs_dir", ".olav/logs")

    @property
    def templates_dir(self) -> str:
        return self._data.get("templates_dir", ".olav/templates")

    @property
    def audit_profiles_dir(self) -> str:
        audit = self._data.get("audit", {})
        return self._loader._env_override(
            "paths",
            "audit_profiles_dir",
            audit.get("profiles_dir", ".olav/workspace/audit/profiles"),
        )

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
    def config_dir(self) -> str:
        return self._data.get("config_dir", ".olav/config")

    @property
    def backup_dir(self) -> str:
        return self._data.get("backup_dir", "exports/backup")

    @property
    def tmp_snapshots_dir(self) -> str:
        return self._data.get("tmp_snapshots_dir", "tmp/snapshots")

    @property
    def tmp_staging_dir(self) -> str:
        return self._data.get("tmp_staging_dir", "tmp/staging")

    @property
    def snapshots_staging_json(self) -> str:
        snapshots = self._data.get("snapshots", {})
        return snapshots.get("staging_json", "exports/snapshots/json")

    @property
    def main_db(self) -> str:
        files = self._data.get("files", {})
        return files.get("main_db", ".olav/databases/main.duckdb")

    @property
    def domain_db(self) -> str:
        """统一域数据存储（所有域数据；内部用 DuckDB Schema 隔离）。"""
        return self.main_db

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


class MemoryConfig:
    """Configuration for the LanceDB OCM (Olav Central Memory) system.

    All values can be overridden via environment variables:
        OLAV_MEMORY_DEDUP_THRESHOLD, OLAV_MEMORY_CACHE_SIMILARITY_THRESHOLD, etc.
    Or via an ``api.json`` top-level ``"memory"`` section.
    """

    def __init__(self, data: dict, loader: "ConfigLoader"):
        self._data = data
        self._loader = loader

    @property
    def dedup_threshold(self) -> float:
        """Vector similarity threshold for dedup (0–1, higher = stricter, default 0.92)."""
        return float(
            self._loader._env_override(
                "memory", "dedup_threshold", self._data.get("dedup_threshold", 0.92)
            )
        )

    @property
    def cache_similarity_threshold(self) -> float:
        """Cosine *distance* below which a query is a cache hit (default 0.02 = 98% similar)."""
        return float(
            self._loader._env_override(
                "memory",
                "cache_similarity_threshold",
                self._data.get("cache_similarity_threshold", 0.02),
            )
        )

    @property
    def fts_rebuild_every(self) -> int:
        """Rebuild the FTS index after this many writes to prevent stale BM25 results (default 20)."""
        return int(
            self._loader._env_override(
                "memory",
                "fts_rebuild_every",
                self._data.get("fts_rebuild_every", 20),
            )
        )

    @property
    def cache_ttl_hours(self) -> int:
        """Semantic cache TTL in hours before entries expire (default 24)."""
        return int(
            self._loader._env_override(
                "memory", "cache_ttl_hours", self._data.get("cache_ttl_hours", 24)
            )
        )

    @property
    def cache_max_entries(self) -> int:
        """Max entries in the semantic cache before oldest are evicted (default 500)."""
        return int(
            self._loader._env_override(
                "memory",
                "cache_max_entries",
                self._data.get("cache_max_entries", 500),
            )
        )


class AuthConfig:
    """Authentication configuration from api.json auth section.

    All values can be overridden via OLAV_AUTH_* environment variables.
    """

    def __init__(self, data: dict, loader: "ConfigLoader"):
        self._data = data
        self._loader = loader

    @property
    def mode(self) -> str:
        """Auth mode: none | token | server | ldap | ad | oidc (default: none).

        none   → Tier 0 OSIdentityProvider (OS $USER)
        token  → Tier 1 TokenAuthProvider (~/.olav/token vs users.duckdb)
        server → Tier 1 ServerTokenProvider (WebUI JupyterLab-style)
        """
        return self._loader._env_override("auth", "mode", self._data.get("mode", "none"))

    @property
    def token_file(self) -> str:
        """Per-user token file path (default: ~/.olav/token)."""
        return self._data.get("token_file", "~/.olav/token")

    @property
    def server_token_file(self) -> str:
        """Server token file path for WebUI mode (default: .olav/run/server.token)."""
        return self._data.get("server_token_file", ".olav/run/server.token")

    @property
    def users_db(self) -> str:
        """Path to users.duckdb (default: .olav/databases/users.duckdb)."""
        return self._data.get("users_db", ".olav/databases/users.duckdb")

    @property
    def session_ttl_hours(self) -> int:
        """Session cookie TTL in hours (default: 24)."""
        return int(self._data.get("session_ttl_hours", 24))

    @property
    def ldap(self) -> dict:
        """LDAP connection config dict: host, port, base_dn, tls."""
        return self._data.get("ldap", {})

    @property
    def ad(self) -> dict:
        """Active Directory config dict: domain, dc_host."""
        return self._data.get("ad", {})

    @property
    def oidc(self) -> dict:
        """OIDC config dict: issuer_url, client_id."""
        return self._data.get("oidc", {})


class DatasetExportConfig:
    def __init__(self, data: dict, loader: "ConfigLoader"):
        self._data = data
        self._loader = loader

    @property
    def encryption_mode(self) -> str:
        return self._loader._env_override(
            "dataset_export", "encryption_mode", self._data.get("encryption_mode", "disabled")
        )

    @property
    def local_train_access_mode(self) -> str:
        return self._loader._env_override(
            "dataset_export",
            "local_train_access_mode",
            self._data.get("local_train_access_mode", "none"),
        )

    @property
    def key_ref(self) -> str:
        return self._loader._env_override(
            "dataset_export", "key_ref", self._data.get("key_ref", "dataset-export-key-v1")
        )

    @property
    def temp_file_policy(self) -> str:
        return self._loader._env_override(
            "dataset_export",
            "temp_file_policy",
            self._data.get("temp_file_policy", "delete_on_success"),
        )

    @property
    def allow_plaintext_stats(self) -> bool:
        return self._loader._env_override(
            "dataset_export",
            "allow_plaintext_stats",
            self._data.get("allow_plaintext_stats", True),
        )

    @property
    def allow_plaintext_rejected_runs(self) -> bool:
        return self._loader._env_override(
            "dataset_export",
            "allow_plaintext_rejected_runs",
            self._data.get("allow_plaintext_rejected_runs", True),
        )

    @property
    def associated_data_version(self) -> str:
        return self._loader._env_override(
            "dataset_export",
            "associated_data_version",
            self._data.get("associated_data_version", "v1"),
        )


class RuntimeConfig:
    def __init__(self, data: dict, loader: ConfigLoader):
        self._data = data
        self._loader = loader

    @property
    def timeout(self) -> int:
        exec_data = self._data.get("execution", {})
        return self._loader._env_override("runtime", "timeout", exec_data.get("timeout", 60))

    @property
    def global_delay_factor(self) -> float:
        exec_data = self._data.get("execution", {})
        return self._loader._env_override(
            "runtime", "global_delay_factor", exec_data.get("global_delay_factor", 1.0)
        )

    @property
    def max_loops(self) -> int:
        exec_data = self._data.get("execution", {})
        return self._loader._env_override("runtime", "max_loops", exec_data.get("max_loops", 3))

    @property
    def log_level(self) -> str:
        log_data = self._data.get("logging", {})
        return self._loader._env_override("runtime", "log_level", log_data.get("level", "INFO"))


_config = None


def get_config() -> ConfigLoader:
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = ConfigLoader()
    return _config


def reload_config():
    global _config
    with _config_lock:
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


def get_memory_config() -> MemoryConfig:
    return get_config().memory


def get_dataset_export_config() -> "DatasetExportConfig":
    return get_config().dataset_export


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
    def agent_dir(self) -> str:
        return get_paths_config().agent_dir

    @property
    def workspace_dir(self) -> str:
        return get_paths_config().workspace_dir

    @property
    def execution(self):
        return get_runtime_config()

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
            # Map internal resolution keys to config property names
            prop_map = {
                "MAIN_DB_PATH": "main_db",
                "DATABASES_DIR": "databases_dir",
                "EXPORTS_DIR": "exports_dir",
                "AUDIT_REPORTS_DIR": "audit_reports_dir",
                "AGENT_OUTPUTS_DIR": "agent_outputs_dir",
                "LOGS_DIR": "logs_dir",
                "KNOWLEDGE_BASE_DIR": "knowledge_dir",
                "WORKSPACE_DIR": "workspace_dir",
                "CONFIG_DIR": "config_dir",
                "SKILLS_DIR": "skills_dir",
                "AGENT_DIR": "agent_dir",
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
MAIN_DB_PATH = _path_resolver.resolve("MAIN_DB_PATH")
DATABASES_DIR = _path_resolver.resolve("DATABASES_DIR")
EXPORTS_DIR = _path_resolver.resolve("EXPORTS_DIR")
AUDIT_REPORTS_DIR = _path_resolver.resolve("AUDIT_REPORTS_DIR")  # Audit inspection reports
AGENT_OUTPUTS_DIR = _path_resolver.resolve(
    "AGENT_OUTPUTS_DIR"
)  # Agent output files (reports, diagrams)
LOGS_DIR = _path_resolver.resolve("LOGS_DIR")
# ── Platform-core path constants ──────────────────────────────────────────────
KNOWLEDGE_BASE_DIR = _path_resolver.resolve("KNOWLEDGE_BASE_DIR")
WORKSPACE_DIR = _path_resolver.resolve("WORKSPACE_DIR")
CONFIG_DIR = _path_resolver.resolve("CONFIG_DIR")
SKILLS_DIR = WORKSPACE_DIR
AGENT_DIR = _path_resolver.resolve("AGENT_DIR")
SKILL_BASE_PATH = WORKSPACE_DIR
UNIFIED_DB = MAIN_DB_PATH  # Legacy alias
DOMAIN_DB_PATH = MAIN_DB_PATH  # Preferred name: domain-scoped unified DB

# User-local paths
try:
    _username = os.environ.get("USER") or os.getlogin()
except Exception:
    _username = os.environ.get("USERNAME", "default_user")

USER_SESSION_DIR = Path.home() / ".olav" / "sessions"

# ── NetOps-specific constants (moved here for backward compat, will migrate to
# ── workspace config/ in M2 — see ISSUE-M2-CONFIG-ARCHITECTURE-REFACTOR) ─────
TEXTFSM_TEMPLATES_DIR = _PROJECT_ROOT / get_paths_config().templates_dir
SNAPSHOTS_DIR = EXPORTS_DIR / "snapshots"
BACKUP_DIR = EXPORTS_DIR / "backup"
TMP_SNAPSHOTS_DIR = _PROJECT_ROOT / get_paths_config().tmp_snapshots_dir
TMP_STAGING_DIR = _PROJECT_ROOT / get_paths_config().tmp_staging_dir
SNAPSHOTS_STAGING_JSON = _PROJECT_ROOT / get_paths_config().snapshots_staging_json
def _resolve_nornir_config_path() -> "Path":
    """Resolve the nornir config path with migration-aware fallback.

    Priority:
    0. Post-R32 collect-scoped path: .olav/workspace/ops/collect/config/nornir/config.yaml
    1. Post-M3 probe-scoped path:   .olav/workspace/ops/probe/config/nornir/config.yaml (pre-R32)
    2. Post-M2 workspace path:      .olav/workspace/ops/config/nornir/config.yaml
    3. Legacy domains path:         .olav/config/domains/netops/nornir/config.yaml
    4. Old flat path:               .olav/config/nornir/config.yaml
    """
    collect_path = AGENT_DIR / "workspace" / "ops" / "collect" / "config" / "nornir" / "config.yaml"
    if collect_path.exists():
        return collect_path
    probe_path = AGENT_DIR / "workspace" / "ops" / "probe" / "config" / "nornir" / "config.yaml"
    if probe_path.exists():
        return probe_path
    ws_path = AGENT_DIR / "workspace" / "ops" / "config" / "nornir" / "config.yaml"
    if ws_path.exists():
        return ws_path
    # LEGACY-KEEP: pre-M2 domain config path. Pre-v0.13 installations still
    # have their nornir config at .olav/config/domains/netops/nornir/; keep
    # this probe until the earliest supported release moves past M2.
    legacy_path = CONFIG_DIR / "domains" / "netops" / "nornir" / "config.yaml"
    if legacy_path.exists():
        return legacy_path
    return CONFIG_DIR / "nornir" / "config.yaml"


NORNIR_CONFIG_PATH = _resolve_nornir_config_path()
NETWORK_DB_PATH = MAIN_DB_PATH
GUARD_WHITELIST_PATH = SKILLS_DIR / "guard" / "whitelist.yaml"

# ── Domain config directory convention ───────────────────────────────────────
# Mapping from domain name to workspace directory name.
# Post-M2: domain config has migrated from .olav/config/domains/<domain>/
# to .olav/workspace/<workspace>/config/.
_DOMAIN_WORKSPACE_MAP: "dict[str, str]" = {
    "netops": "ops",
}


def get_domain_config_dir(domain: str) -> "Path":
    """Return the config directory for *domain*.

    Checks the workspace-based path first (post-M2 migration), then falls
    back to the legacy ``.olav/config/domains/<domain>/`` path.

    The directory is not created by this function; callers are responsible
    for ensuring it exists when needed.

    Parameters
    ----------
    domain:
        Domain package name, e.g. ``"netops"``.

    Returns
    -------
    Path
        Absolute path to the domain config directory.
    """
    ws_name = _DOMAIN_WORKSPACE_MAP.get(domain)
    if ws_name:
        ws_config = AGENT_DIR / "workspace" / ws_name / "config"
        if ws_config.is_dir():
            return ws_config
    return CONFIG_DIR / "domains" / domain


LOG_STORAGE_DIR = DATABASES_DIR / "logs"  # Syslog receiver storage directory
AUDIT_DB_PATH = DATABASES_DIR / "audit.duckdb"  # Audit event store (append-only)
CACHE_DIR = AGENT_DIR / "cache"  # Legacy: project-level cache (kept for backwards compat)
USER_CACHE_DIR = Path.home() / ".olav" / "cache" / _username  # User-isolated LLM cache
USER_CHECKPOINT_DIR = Path.home() / ".olav" / "checkpoints" / _username  # User-isolated checkpoints


__all__ = [
    "settings",
    "Settings",
    "get_settings",
    "MAIN_DB_PATH",
    "DATABASES_DIR",
    "EXPORTS_DIR",
    "LOGS_DIR",
    "TEXTFSM_TEMPLATES_DIR",
    "KNOWLEDGE_BASE_DIR",
    "WORKSPACE_DIR",
    "CONFIG_DIR",
    "SKILLS_DIR",
    "AGENT_DIR",
    "SKILL_BASE_PATH",
    "UNIFIED_DB",
    "SNAPSHOTS_DIR",
    "BACKUP_DIR",
    "TMP_SNAPSHOTS_DIR",
    "TMP_STAGING_DIR",
    "SNAPSHOTS_STAGING_JSON",
    "NORNIR_CONFIG_PATH",
    "NETWORK_DB_PATH",
    "USER_SESSION_DIR",
    "GUARD_WHITELIST_PATH",
    "LOG_STORAGE_DIR",
    "AUDIT_DB_PATH",
    "CACHE_DIR",
    "USER_CACHE_DIR",
    "USER_CHECKPOINT_DIR",
    "get_config",
    "get_domain_config_dir",
    "get_llm_config",
    "get_embedding_config",
    "get_paths_config",
    "get_runtime_config",
    "get_memory_config",
    "get_dataset_export_config",
    "MemoryConfig",
    "AuthConfig",
    "DatasetExportConfig",
]
