"""
Feature Flag Management for OLAV

Supports:
- Runtime enable/disable of features (Guard, metrics, etc.)
- Percentage-based rollout (0-100%)
- User segment support (admin, internal, all)
- Consistent user bucketing (hash-based, same user gets same treatment)
- Hot-reload support
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class FeatureFlagConfig:
    """Configuration for a single feature flag"""
    
    enabled: bool = True
    rollout_percentage: int = field(
        default=100,
        metadata={"description": "Percentage of users to enable feature for (0-100)"}
    )
    rollout_user_segment: Literal["all", "admin", "internal", "beta"] = field(
        default="all",
        metadata={"description": "User segment for rollout"}
    )
    metrics_enabled: bool = field(
        default=True,
        metadata={"description": "Collect metrics for this feature"}
    )
    
    def __post_init__(self):
        """Validate configuration"""
        if not 0 <= self.rollout_percentage <= 100:
            raise ValueError(f"rollout_percentage must be 0-100, got {self.rollout_percentage}")


class FeatureFlagManager:
    """
    Manages feature flags with percentage-based rollout support.
    
    Usage:
    ```python
    from olav.core.feature_flags import get_feature_flag_manager
    
    manager = get_feature_flag_manager()
    
    # Check if Guard is enabled for this user
    if manager.is_enabled("guard_routing", user_id="user123"):
        # Use Guard routing
        ...
    else:
        # Use Orchestrator (baseline)
        ...
    
    # Get feature config
    config = manager.get_feature_config("guard_routing")
    print(f"Rollout: {config.rollout_percentage}%")
    
    # Update flag at runtime
    manager.update_flag("guard_routing", rollout_percentage=50)
    ```
    """
    
    def __init__(self):
        """Initialize Feature Flag Manager"""
        self.flags: dict[str, FeatureFlagConfig] = {}
        self.config_file: Path | None = None
        self._load_default_flags()
    
    def _load_default_flags(self):
        """Load default feature flags"""
        # Guard: Default enabled at 100%
        self.flags["guard_routing"] = FeatureFlagConfig(
            enabled=True,
            rollout_percentage=100,
            rollout_user_segment="all",
            metrics_enabled=True,
        )
        
        # Metrics collection: Default enabled
        self.flags["metrics_collection"] = FeatureFlagConfig(
            enabled=True,
            rollout_percentage=100,
            rollout_user_segment="all",
            metrics_enabled=True,
        )
    
    def set_config_file(self, config_file: Path | str):
        """Set path to configuration file"""
        self.config_file = Path(config_file)
    
    def load_from_file(self, config_file: Path | str) -> bool:
        """
        Load feature flags from configuration file.
        
        Args:
            config_file: Path to JSON config file with feature_flags section
            
        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            config_file = Path(config_file)
            if not config_file.exists():
                logger.debug(f"Feature flags file not found: {config_file}")
                return False
            
            with open(config_file) as f:
                config = json.load(f)
            
            feature_flags = config.get("feature_flags", {})
            if not feature_flags:
                logger.debug(f"No feature_flags section in {config_file}")
                return False
            
            # Load each flag
            for flag_name, flag_config in feature_flags.items():
                if isinstance(flag_config, dict):
                    try:
                        self.flags[flag_name] = FeatureFlagConfig(**flag_config)
                        logger.info(f"Loaded feature flag: {flag_name}")
                    except (TypeError, ValueError) as e:
                        logger.error(f"Invalid feature flag config for {flag_name}: {e}")
                        return False
            
            self.config_file = config_file
            return True
            
        except Exception as e:
            logger.error(f"Failed to load feature flags from {config_file}: {e}")
            return False
    
    def load_from_dict(self, config: dict[str, dict[str, Any]]) -> bool:
        """
        Load feature flags from dictionary.
        
        Args:
            config: Dictionary with 'feature_flags' key
            
        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            feature_flags = config.get("feature_flags", {})
            if not feature_flags:
                logger.debug("No feature_flags section in config")
                return False
            
            for flag_name, flag_config in feature_flags.items():
                if isinstance(flag_config, dict):
                    try:
                        self.flags[flag_name] = FeatureFlagConfig(**flag_config)
                    except (TypeError, ValueError) as e:
                        logger.error(f"Invalid feature flag config for {flag_name}: {e}")
                        return False
            
            return True
        except Exception as e:
            logger.error(f"Failed to load feature flags: {e}")
            return False
    
    def is_enabled(
        self,
        flag_name: str,
        user_id: str | None = None,
        user_segment: str | None = None,
    ) -> bool:
        """
        Check if a feature flag is enabled for a user.
        
        Uses consistent hashing to ensure same user always gets same treatment.
        
        Args:
            flag_name: Name of feature flag
            user_id: User ID for bucketing (if None, uses random bucketing)
            user_segment: User segment (admin, internal, all, etc.)
            
        Returns:
            True if feature is enabled for this user, False otherwise
        """
        if flag_name not in self.flags:
            logger.warning(f"Unknown feature flag: {flag_name}")
            return False
        
        config = self.flags[flag_name]
        
        # Check if feature is globally disabled
        if not config.enabled:
            return False
        
        # Check rollout percentage
        if config.rollout_percentage == 0:
            return False
        
        if config.rollout_percentage == 100:
            return True
        
        # Percentage-based bucketing: use user_id hash
        if user_id:
            bucket = self._hash_user_to_bucket(user_id)
        else:
            # If no user_id, use random bucketing (not consistent)
            import random
            bucket = random.randint(0, 99)
        
        return bucket < config.rollout_percentage
    
    def _hash_user_to_bucket(self, user_id: str) -> int:
        """
        Hash user_id to consistent bucket (0-99).
        
        Same user_id always gets same bucket.
        """
        hash_digest = hashlib.md5(user_id.encode()).hexdigest()
        hash_int = int(hash_digest, 16)
        bucket = hash_int % 100
        return bucket
    
    def get_feature_config(self, flag_name: str) -> FeatureFlagConfig | None:
        """Get configuration for a feature flag"""
        return self.flags.get(flag_name)
    
    def update_flag(
        self,
        flag_name: str,
        enabled: bool | None = None,
        rollout_percentage: int | None = None,
        rollout_user_segment: str | None = None,
        metrics_enabled: bool | None = None,
    ) -> bool:
        """
        Update feature flag configuration at runtime.
        
        Args:
            flag_name: Name of feature flag
            enabled: New enabled status
            rollout_percentage: New rollout percentage (0-100)
            rollout_user_segment: New user segment
            metrics_enabled: New metrics status
            
        Returns:
            True if updated successfully, False otherwise
        """
        if flag_name not in self.flags:
            logger.error(f"Unknown feature flag: {flag_name}")
            return False
        
        config = self.flags[flag_name]
        
        # Validate and update
        try:
            if enabled is not None:
                config.enabled = enabled
            
            if rollout_percentage is not None:
                if not 0 <= rollout_percentage <= 100:
                    raise ValueError(f"rollout_percentage must be 0-100")
                config.rollout_percentage = rollout_percentage
            
            if rollout_user_segment is not None:
                if rollout_user_segment not in ["all", "admin", "internal", "beta"]:
                    raise ValueError(f"Invalid user_segment: {rollout_user_segment}")
                config.rollout_user_segment = rollout_user_segment
            
            if metrics_enabled is not None:
                config.metrics_enabled = metrics_enabled
            
            logger.info(f"Updated feature flag: {flag_name} -> {config}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update feature flag {flag_name}: {e}")
            return False
    
    def get_all_flags(self) -> dict[str, FeatureFlagConfig]:
        """Get all feature flags"""
        return dict(self.flags)
    
    def reload(self):
        """Reload feature flags from file"""
        if self.config_file:
            self.load_from_file(self.config_file)
            logger.info(f"Reloaded feature flags from {self.config_file}")
        else:
            logger.warning("No config file set, cannot reload feature flags")


# Global singleton instance
_feature_flag_manager: FeatureFlagManager | None = None


def get_feature_flag_manager() -> FeatureFlagManager:
    """Get or create singleton feature flag manager"""
    global _feature_flag_manager
    if _feature_flag_manager is None:
        _feature_flag_manager = FeatureFlagManager()
    return _feature_flag_manager


def reset_feature_flag_manager():
    """Reset singleton (for testing)"""
    global _feature_flag_manager
    _feature_flag_manager = None
