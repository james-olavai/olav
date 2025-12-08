"""OLAV Configuration Package.

Single configuration entry point - all config from .env via EnvSettings.
"""

from config.settings import (
    EnvSettings,
    settings,
    PROJECT_ROOT,
    ENV_FILE_PATH,
    DATA_DIR,
    CONFIG_DIR,
    get_path,
)

__all__ = [
    "EnvSettings",
    "settings",
    "PROJECT_ROOT",
    "ENV_FILE_PATH",
    "DATA_DIR",
    "CONFIG_DIR",
    "get_path",
]
