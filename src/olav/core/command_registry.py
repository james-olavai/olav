#!/usr/bin/env python3
"""
Command Registry - Hot-reload mechanism for templates and commands

Provides singleton registry for TextFSM templates and command definitions.
Supports hot-reload without restarting the process.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CommandRegistry:
    """Global registry for commands and templates.
    
    Singleton pattern for managing:
    - TextFSM templates
    - Whitelisted commands
    - Blacklisted commands
    
    Supports hot-reload via reload() method.
    """
    
    _instance = None
    _templates: dict[str, Path] = {}
    _whitelist: set[str] = set()
    _blacklist: list[str] = []
    _template_index: dict[str, dict] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_all()
        return cls._instance
    
    def _load_all(self):
        """Load all registry data."""
        self._load_templates()
        self._load_whitelist()
        self._load_blacklist()
    
    def _load_templates(self):
        """Load TextFSM templates from .olav/templates/."""
        self._templates.clear()
        self._template_index.clear()
        
        # Priority 1: Custom config directory
        custom_config_dir = Path(".olav/config/textfsm")
        if custom_config_dir.exists():
            self._scan_templates(custom_config_dir, priority=1)
        
        # Priority 2: Command learner custom directory
        custom_dir = Path(".olav/templates/custom")
        if custom_dir.exists():
            self._scan_templates(custom_dir, priority=2)
        
        # Priority 3: Default templates directory
        templates_dir = Path(".olav/templates")
        if templates_dir.exists():
            self._scan_templates(templates_dir, priority=3)
        
        logger.info(f"Loaded {len(self._templates)} TextFSM templates")
    
    def _scan_templates(self, directory: Path, priority: int):
        """Scan directory for TextFSM templates."""
        for template_path in directory.glob("*.textfsm"):
            template_name = template_path.name
            # Only add if not already registered (higher priority wins)
            if template_name not in self._templates:
                self._templates[template_name] = template_path
                self._template_index[template_name] = {
                    "path": str(template_path),
                    "priority": priority,
                    "size": template_path.stat().st_size
                }
    
    def _load_whitelist(self):
        """Load whitelisted commands from config."""
        self._whitelist.clear()
        
        whitelist_path = Path(".olav/config/allowed_commands.json")
        if whitelist_path.exists():
            try:
                import json
                data = json.loads(whitelist_path.read_text())
                commands = data.get("commands", [])
                self._whitelist.update(commands)
                logger.info(f"Loaded {len(self._whitelist)} whitelisted commands")
            except Exception as e:
                logger.error(f"Failed to load whitelist: {e}")
    
    def _load_blacklist(self):
        """Load blacklisted commands from config."""
        self._blacklist.clear()
        
        blacklist_path = Path(".olav/config/blacklisted_commands.json")
        if blacklist_path.exists():
            try:
                import json
                data = json.loads(blacklist_path.read_text())
                patterns = data.get("patterns", [])
                self._blacklist.extend(patterns)
                logger.info(f"Loaded {len(self._blacklist)} blacklisted patterns")
            except Exception as e:
                logger.error(f"Failed to load blacklist: {e}")
    
    @classmethod
    def reload(cls) -> dict[str, Any]:
        """Hot-reload all command definitions.
        
        Reloads:
        1. TextFSM templates (.olav/templates/*)
        2. Command whitelist (.olav/config/allowed_commands.json)
        3. Command blacklist (.olav/config/blacklisted_commands.json)
        
        Returns:
            dict: {
                "reloaded": {
                    "templates": int,
                    "whitelisted_commands": int,
                    "blacklisted_patterns": int
                },
                "new_templates": list[str],
                "errors": list[str]
            }
        """
        if cls._instance is None:
            cls._instance = cls()
        
        # Track changes
        old_templates = set(cls._instance._templates.keys())
        
        # Reload all
        try:
            cls._instance._load_all()
            
            # Detect new templates
            new_templates = list(set(cls._instance._templates.keys()) - old_templates)
            
            logger.info(f"✅ Reloaded: {len(cls._instance._templates)} templates, "
                       f"{len(cls._instance._whitelist)} commands, "
                       f"{len(cls._instance._blacklist)} blacklist patterns")
            
            return {
                "reloaded": {
                    "templates": len(cls._instance._templates),
                    "whitelisted_commands": len(cls._instance._whitelist),
                    "blacklisted_patterns": len(cls._instance._blacklist)
                },
                "new_templates": new_templates,
                "errors": []
            }
            
        except Exception as e:
            logger.error(f"Failed to reload: {e}")
            return {
                "reloaded": {
                    "templates": 0,
                    "whitelisted_commands": 0,
                    "blacklisted_patterns": 0
                },
                "new_templates": [],
                "errors": [str(e)]
            }
    
    @classmethod
    def get_template_path(cls, template_name: str) -> Path | None:
        """Get path for a template by name."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance._templates.get(template_name)
    
    @classmethod
    def is_command_allowed(cls, command: str) -> bool:
        """Check if command is whitelisted."""
        if cls._instance is None:
            cls._instance = cls()
        return command in cls._instance._whitelist
    
    @classmethod
    def is_command_blacklisted(cls, command: str) -> bool:
        """Check if command matches blacklist pattern."""
        if cls._instance is None:
            cls._instance = cls()
        
        import re
        for pattern in cls._instance._blacklist:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False
    
    @classmethod
    def get_all_templates(cls) -> dict[str, dict]:
        """Get all registered templates."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance._template_index


# Create singleton instance on module import
_registry = CommandRegistry()
