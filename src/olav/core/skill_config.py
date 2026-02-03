"""SkillConfig - Load cache and behavior configuration from SKILL.md frontmatter.

This module provides utilities to load SKILL.md configurations, enabling
per-skill customization of caching strategies, execution modes, and other
behavioral parameters.
"""

import logging
import time
from pathlib import Path
from typing import Any

import yaml

from config.paths import SKILLS_DIR

logger = logging.getLogger(__name__)


class SkillConfig:
    """Load and manage SKILL.md configuration from frontmatter."""

    # 启动时缓存所有skill配置
    _config_cache: dict[str, dict[str, Any]] = {}
    _initialized: bool = False

    @classmethod
    def initialize(cls) -> None:
        """
        Initialize SkillConfig by preloading all skill configurations.

        Call this once at application startup to avoid repeated disk I/O
        and YAML parsing during request handling.

        Performance: ~100ms (one-time cost at startup)
        """
        if cls._initialized:
            logger.debug("SkillConfig already initialized, skipping")
            return

        start_time = time.time()
        count = 0
        errors = 0

        try:
            skills_path = Path(SKILLS_DIR)
            if not skills_path.exists():
                logger.warning(f"SKILLS_DIR not found: {skills_path}")
                cls._initialized = True
                return

            for skill_dir in skills_path.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_id = skill_dir.name
                try:
                    config = cls._load_skill_frontmatter(skill_id)
                    cls._config_cache[skill_id] = config or {}
                    count += 1
                except Exception as e:
                    logger.error(f"Error loading config for skill {skill_id}: {e}")
                    errors += 1

        except Exception as e:
            logger.error(f"Error initializing SkillConfig: {e}")
            errors += 1

        cls._initialized = True
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"✅ SkillConfig initialized: {count} skills loaded in {elapsed_ms:.2f}ms "
            f"(errors: {errors})"
        )

    @staticmethod
    def get_cache_config(skill_id: str) -> dict[str, Any]:
        """
        Get cache configuration for a specific skill.

        This method uses the preloaded config cache for O(1) lookup.
        If not initialized yet, it will be initialized on first call.

        Args:
            skill_id: Skill identifier (e.g., "network-query")

        Returns:
            Cache configuration dict with keys:
            - enabled: bool (default: True)
            - match_mode: "exact" | "fuzzy" | "semantic" (default: "exact")
            - confidence_threshold: float (default: 1.0)
            - ttl_hours: int (default: 168)
        """
        # 确保已初始化
        if not SkillConfig._initialized:
            SkillConfig.initialize()

        # O(1) 从内存缓存查询
        skill_config = SkillConfig._config_cache.get(skill_id, {})

        cache_cfg = skill_config.get("cache", {})

        # Apply defaults for missing keys
        return {
            "enabled": cache_cfg.get("enabled", True),
            "match_mode": cache_cfg.get("match_mode", "exact"),
            "confidence_threshold": cache_cfg.get("confidence_threshold", 1.0),
            "ttl_hours": cache_cfg.get("ttl_hours", 168),
        }

    @staticmethod
    def _load_skill_frontmatter(skill_id: str) -> dict[str, Any] | None:
        """
        Load SKILL.md frontmatter for a specific skill.

        Args:
            skill_id: Skill identifier

        Returns:
            Frontmatter dict or None if not found
        """
        skill_path = Path(SKILLS_DIR) / skill_id / "SKILL.md"

        if not skill_path.exists():
            logger.warning(f"SKILL.md not found: {skill_path}")
            return None

        try:
            with open(skill_path, encoding="utf-8") as f:
                content = f.read()

                # Parse frontmatter (YAML between --- markers)
                if not content.startswith("---"):
                    logger.warning(f"Invalid SKILL.md format: {skill_path}")
                    return None

                # Find second --- marker
                lines = content.split("\n")
                frontmatter_end = None
                for i in range(1, len(lines)):
                    if lines[i].startswith("---"):
                        frontmatter_end = i
                        break

                if frontmatter_end is None:
                    logger.warning(f"No closing --- found in: {skill_path}")
                    return None

                # Parse YAML
                frontmatter_text = "\n".join(lines[1:frontmatter_end])
                return yaml.safe_load(frontmatter_text)

        except Exception as e:
            logger.error(f"Error loading SKILL.md {skill_path}: {e}")
            return None

    @staticmethod
    def _default_cache_config() -> dict[str, Any]:
        """Get default cache configuration."""
        return {
            "enabled": True,
            "match_mode": "exact",
            "confidence_threshold": 1.0,
            "ttl_hours": 168,
        }

    @staticmethod
    def get_execution_config(skill_id: str) -> dict[str, Any]:
        """
        Get execution configuration for a specific skill.

        Args:
            skill_id: Skill identifier

        Returns:
            Execution configuration dict
        """
        skill_config = SkillConfig._load_skill_frontmatter(skill_id)

        if not skill_config:
            return {}

        return skill_config.get("execution", {})

    @staticmethod
    def is_skill_enabled(skill_id: str) -> bool:
        """
        Check if a skill is enabled.

        Args:
            skill_id: Skill identifier

        Returns:
            True if enabled (default), False otherwise
        """
        skill_config = SkillConfig._load_skill_frontmatter(skill_id)

        if not skill_config:
            return True  # Default to enabled

        return skill_config.get("enabled", True)
