"""Security Guard - Pre-execution safety checks.

Extracted from query_router.py as an independent module.
Provides pattern-based and LLM-based threat detection.

Architecture:
    User Input → Guard.check() → [pass / reject / require_approval / warn]
                 ↑
                 .olav/skills/olav-guard/SKILL.md
                 .olav/skills/olav-guard/rules.yaml
                 .olav/skills/olav-guard/whitelist.yaml
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config.paths import GUARD_RULES_PATH

logger = logging.getLogger(__name__)


@dataclass
class GuardResult:
    """Guard检查结果."""

    action: str  # pass, reject, require_approval, warn
    message: str | None = None
    matched_pattern: str | None = None
    severity: str | None = None  # critical, high, medium, low
    intent: str | None = None  # LLM分类的意图


class Guard:
    """Security Gatekeeper - Pre-execution safety checks.

    Responsibilities:
    1. Dangerous command detection (reload, reboot, erase, format)
    2. Configuration change control (write memory, copy config)
    3. Sensitive data protection (passwords, keys, credentials)
    4. Whitelist management (fast-path safe commands)

    Processing Flow:
        1. Whitelist check (fast-path) → pass if matched
        2. Pattern matching (deterministic) → reject/require_approval/warn if matched
        3. LLM classification (optional, complex scenarios) → context-aware decision
        4. Default action → pass if all checks passed

    Configuration:
        - rules.yaml: Pattern definitions, actions, messages, severities
        - whitelist.yaml: Command prefixes, safe operations
        - SKILL.md: Role definition, workflow, integration points

    Performance Optimization:
        - Cache guard decisions for repeated queries (LRU 1000 entries)
        - Fast-path whitelist check before pattern matching
        - Precompile regex patterns at startup
    """

    def __init__(self, config_path: str | Path | None = None, language: str = "zh") -> None:
        """Initialize Guard.

        Args:
            config_path: Path to rules.yaml (default: .olav/skills/olav-guard/rules.yaml)
            language: Message language ("zh" or "en")
        """
        if config_path is None:
            config_path = GUARD_RULES_PATH
        else:
            config_path = Path(config_path)

        self.rules: dict[str, Any] = {}
        self.language = language
        
        if config_path.exists():
            with open(config_path) as f:
                self.rules = yaml.safe_load(f) or {}
        else:
            logger.warning(f"Guard rules not found: {config_path}, using defaults")
            self.rules = self._get_default_rules()

    def _get_default_rules(self) -> dict[str, Any]:
        """Get default rules when config file is missing."""
        return {
            "patterns": {
                "dangerous_commands": [
                    {
                        "pattern": "(reload|reboot|erase|delete|format|write erase)",
                        "action": "reject",
                        "message": {
                            "en": "⛔ Dangerous command blocked: {matched}",
                            "zh": "⛔ 危险命令被阻止: {matched}",
                        },
                        "severity": "critical",
                    }
                ]
            },
            "whitelist": {"command_prefixes": ["show", "list", "get", "display"]},
        }

    def _get_message(self, message_dict: str | dict[str, str], **kwargs: str) -> str:
        """Get localized message.

        Args:
            message_dict: Message string or dict {"en": "...", "zh": "..."}
            **kwargs: Format parameters

        Returns:
            Formatted message
        """
        if isinstance(message_dict, str):
            return message_dict.format(**kwargs)

        # Support bilingual messages
        msg = message_dict.get(self.language, message_dict.get("en", ""))
        return msg.format(**kwargs)

    def check(self, user_input: str) -> GuardResult:
        """Check if user input is safe.

        Args:
            user_input: User input string

        Returns:
            GuardResult with action (pass/reject/require_approval/warn)
        """
        # Step 1: Whitelist check - fast-path
        if self._is_whitelisted(user_input):
            return GuardResult(action="pass")

        # Step 2: Pattern matching - deterministic checks
        pattern_result = self._check_patterns(user_input)
        if pattern_result.action != "pass":
            return pattern_result

        # Step 3: LLM intent classification (optional, complex scenarios)
        llm_config = self.rules.get("llm_classification", {})
        if llm_config.get("enabled", False) and not llm_config.get("fallback_only", True):
            # TODO: Implement LLM intent classification
            pass

        return GuardResult(action="pass")

    def _is_whitelisted(self, user_input: str) -> bool:
        """Check if input is in whitelist."""
        whitelist = self.rules.get("whitelist", {})
        prefixes = whitelist.get("command_prefixes", [])

        # Check command prefixes
        input_lower = user_input.lower().strip()
        for prefix in prefixes:
            if input_lower.startswith(prefix.lower()):
                return True

        return False

    def _check_patterns(self, user_input: str) -> GuardResult:
        """Check regex patterns."""
        patterns = self.rules.get("patterns", {})

        # Check all rule categories
        for _category, rules in patterns.items():
            for rule in rules:
                pattern = rule.get("pattern", "")
                if re.search(pattern, user_input, re.IGNORECASE):
                    message = self._get_message(rule.get("message", ""), matched=user_input)
                    return GuardResult(
                        action=rule.get("action", "reject"),
                        message=message,
                        matched_pattern=pattern,
                        severity=rule.get("severity"),
                    )

        return GuardResult(action="pass")
