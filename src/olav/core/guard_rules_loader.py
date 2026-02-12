"""
Guard Rules Loader - Parse Guard classification rules from SKILL.md

Purpose:
  Load Guard classification rules from .olav/skills/olav-guard/SKILL.md instead of hardcoding
  Supports dynamic rule updates without code changes
  Respects: SKILL.md → .olav/settings.json → .env override chain

Architecture:
  1. Parse SKILL.md YAML frontmatter
  2. Extract route_categories detection_patterns
  3. Support user overrides in .olav/settings.json
  4. Support environment variable overrides in .env

Principle: SKILL.md is the single source of truth for rules
"""

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

from config.paths import AGENT_DIR, SKILLS_DIR

logger = logging.getLogger(__name__)


class GuardRulesLoader:
    """Load and cache Guard classification rules from SKILL.md."""
    
    SKILL_PATH = SKILLS_DIR / "guard" / "SKILL.md"
    
    # Default rules (fallback if SKILL.md cannot be parsed)
    DEFAULT_RULES = {
        "dangerous_patterns": [
            r"\b(DELETE|DROP|ERASE|FORMAT|DESTROY|TRUNCATE)\b.*\b(ALL|DATABASE|TABLE|INTERFACE|VLAN)\b",
            r"\b(shutdown|reload|reboot|restart|reset)\b",
            r"\bno\s+(ip|interface|routing|vlan|ospf|bgp)",
            r"\brm\s+-rf\b",
            r"\b(pkill|killall)\b",
            r"\b(drop|truncate|delete)\s+(table|database|schema)\b",
            r"\b(inject|exploit|hack|backdoor|vulnerability)\b",
            r"\b(password|secret|api_key|token).*leak",
            r"(删除|销毁|清空).*所有",
            r"执行.*任意.*代码",
            r"(泄露|泄露密码|泄露token)",
        ],
        "simple_indicators": [
            # 🔥 Ultra-conservative: Default to SIMPLE for database queries
            r"\b(count|how many|多少|几个)\b",
            r"^(count|list|show|display|export|save)\b",
            r"\ball\s+(devices|interfaces|routers|switches|neighbors|peers)\b",
            r"\b列出|列示\b.*所有",
            r"\b(name|ip|address|id|status|type)\b",
            # Query/export matching
            r"query.*from|SELECT.*FROM|导出|export.*data|匹配.*导出",
            # Safety net: show/query without real-time context → SIMPLE
            # This is checked specially in _fast_heuristic_check() code
        ],
        "cli_indicators": [
            # 🔥 ULTRA-CONSERVATIVE: Only explicit real-time requests
            r"(?:实时|real-time|live|当前|立即|现在|最新|即刻|马上|正在|目前).*show",
            r"show.*(?:实时|real-time|live|当前|立即|现在|最新|即刻|马上|正在|目前)",
            r"(?:获取|fetch|get|retrieve).*(?:实时|live|current|now)",
        ],
        "expert_indicators": [
            r"^(why|how to|analyze|diagnose|optimize|recommend|趋势|分析|诊断|优化)\b",
            r"\b(root cause|rca|troubleshooting|故障排查|性能分析)\b",
            r"\b(design|architecture|best practice|capacity|scaling|最佳实践)\b",
            r"\b(top|highest|lowest|average|median|percentile)\b",
            r"\b(比较|对比|关系|correlation|relationship|trend)\b",
        ],
        "multi_agent_indicators": [
            r"\b(compare|versus|vs|vs\.|对比|对照|验证|验证一致性|cross-check|交叉检查|一致性)\b",
            r"\bnetbox.*(?:and|与|vs|versus|和)\s*(?:database|db|数据库)",
            r"\b(?:database|db|数据库)\s*(?:and|与|vs|versus|和)\s*netbox",
            r"\bdns.*(?:and|与|vs|versus|和).*(?:ip|database)",
            r"\bverify.*dns",
            r"\b(?:snapshot|backup|历史).*(?:and|与|vs|versus|和)\s*(?:current|live|real-time|当前|实时)",
            r"\bcompare.*(?:snapshot|backup)",
            r"\bacross.*(?:system|database|source)",
            r"\b(?:two|multiple|多个).*(?:source|system|database)\b",
        ],
    }
    
    def __init__(self):
        """Initialize rules loader."""
        self._rules = None
        self._load_timestamp = None
    
    @property
    def rules(self) -> dict[str, list[str]]:
        """Get classification rules (lazy load and cache)."""
        if self._rules is None:
            self._rules = self._load_rules()
        return self._rules
    
    def _load_rules(self) -> dict[str, list[str]]:
        """Load rules from SKILL.md with user overrides."""
        rules = self._load_from_skill()
        
        # 🔥 Phase 2.3-2.4: Load realtime and TextFSM rules
        self._load_realtime_rules(rules)
        self._load_textfsm_rules(rules)
        
        # Apply user overrides from .olav/settings.json
        rules = self._apply_settings_overrides(rules)
        
        # Apply environment variable overrides
        rules = self._apply_env_overrides(rules)
        
        logger.info(f"✅ Guard rules loaded: {list(rules.keys())}")
        return rules
    
    def _load_realtime_rules(self, rules: dict[str, list]) -> None:
        """🔥 Phase 2.3: Load realtime indicators from SKILL.md."""
        try:
            with self.SKILL_PATH.open() as f:
                content = f.read()
            
            # Extract CLI section
            cli_match = re.search(
                r"CLI:\s*\n.*?realtime_indicators:(.*?)(?=\n\s{2,4}\w+:|$)",
                content,
                re.DOTALL
            )
            
            if cli_match:
                realtime_section = cli_match.group(1)
                
                # Extract all keywords (chinese + english)
                keywords = re.findall(r'-\s*"([^"]+)"', realtime_section)
                rules["realtime_indicators"] = keywords
                logger.debug(f"Loaded {len(keywords)} realtime keywords")
            else:
                rules["realtime_indicators"] = [
                    "实时", "当前", "立即", "现在", "最新",
                    "real-time", "realtime", "live", "current", "now"
                ]
                logger.debug("Using default realtime keywords")
            
            # Extract force_live_scenarios
            force_live_match = re.search(
                r"force_live_scenarios:(.*?)(?=\n\s{2,4}\w+:|textfsm_routing:)",
                content,
                re.DOTALL
            )
            
            if force_live_match:
                scenarios_section = force_live_match.group(1)
                scenarios = []
                
                # Parse each scenario
                for scenario_block in re.finditer(
                    r'-\s*pattern:\s*"([^"]+)"\s*reason:\s*"([^"]+)"',
                    scenarios_section
                ):
                    scenarios.append({
                        "pattern": scenario_block.group(1),
                        "reason": scenario_block.group(2)
                    })
                
                rules["force_live_scenarios"] = scenarios
                logger.debug(f"Loaded {len(scenarios)} force_live scenarios")
            else:
                rules["force_live_scenarios"] = []
        
        except Exception as e:
            logger.warning(f"Failed to load realtime rules from SKILL.md: {e}")
            rules["realtime_indicators"] = []
            rules["force_live_scenarios"] = []
    
    def _load_textfsm_rules(self, rules: dict[str, list]) -> None:
        """🔥 Phase 2.4: Load TextFSM routing rules from SKILL.md."""
        try:
            with self.SKILL_PATH.open() as f:
                content = f.read()
            
            # Extract textfsm_routing section
            textfsm_match = re.search(
                r"textfsm_routing:(.*?)(?=\n\s{2,4}characteristics:)",
                content,
                re.DOTALL
            )
            
            if textfsm_match:
                textfsm_section = textfsm_match.group(1)
                
                # Extract prefer_structured_commands
                commands = re.findall(r'-\s*"([^"]+)"', textfsm_section)
                rules["prefer_structured_commands"] = commands
                logger.debug(f"Loaded {len(commands)} prefer_structured commands")
                
                # Extract force_raw_scenarios
                force_raw_matches = re.finditer(
                    r'-\s*pattern:\s*"([^"]+)"\s*reason:\s*"([^"]+)"',
                    textfsm_section
                )
                scenarios = [
                    {"pattern": m.group(1), "reason": m.group(2)}
                    for m in force_raw_matches
                ]
                rules["force_raw_scenarios"] = scenarios
                logger.debug(f"Loaded {len(scenarios)} force_raw scenarios")
            else:
                # Defaults
                rules["prefer_structured_commands"] = [
                    "show interfaces", "show ip interface brief",
                    "show version", "show ip ospf neighbor"
                ]
                rules["force_raw_scenarios"] = []
                logger.debug("Using default TextFSM rules")
        
        except Exception as e:
            logger.warning(f"Failed to load TextFSM rules from SKILL.md: {e}")
            rules["prefer_structured_commands"] = []
            rules["force_raw_scenarios"] = []
    
    def _load_from_skill(self) -> dict[str, list[str]]:
        """Load rules from SKILL.md frontmatter."""
        try:
            if not self.SKILL_PATH.exists():
                logger.warning(f"⚠️ SKILL.md not found: {self.SKILL_PATH}, using defaults")
                return self.DEFAULT_RULES.copy()
            
            with open(self.SKILL_PATH, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract YAML frontmatter
            if not content.startswith('---'):
                logger.warning("⚠️ SKILL.md has no YAML frontmatter, using defaults")
                return self.DEFAULT_RULES.copy()
            
            # Split by --- to get frontmatter
            parts = content.split('---', 2)
            if len(parts) < 3:
                logger.warning("⚠️ Invalid SKILL.md format, using defaults")
                return self.DEFAULT_RULES.copy()
            
            # Parse YAML frontmatter
            yaml_content = parts[1]
            skill_data = yaml.safe_load(yaml_content)
            
            if not skill_data:
                logger.warning("⚠️ Failed to parse SKILL.md YAML, using defaults")
                return self.DEFAULT_RULES.copy()
            
            # Extract rules from route_categories
            rules = self.DEFAULT_RULES.copy()
            
            if "classification_pipeline" in skill_data:
                pipeline = skill_data["classification_pipeline"]
                
                # Stage 3 heuristic rules
                if "stage_3_heuristic_matching" in pipeline:
                    stage3 = pipeline["stage_3_heuristic_matching"]
                    heuristics = stage3.get("heuristic_rules", {})
                    
                    # Update each route type's indicators
                    # Extract "patterns" list from each heuristic rule
                    if "SIMPLE" in heuristics:
                        simple_rule = heuristics["SIMPLE"]
                        if isinstance(simple_rule, dict) and "patterns" in simple_rule:
                            rules["simple_indicators"] = simple_rule["patterns"]
                        else:
                            rules["simple_indicators"] = simple_rule
                    
                    if "CLI" in heuristics:
                        cli_rule = heuristics["CLI"]
                        if isinstance(cli_rule, dict) and "patterns" in cli_rule:
                            rules["cli_indicators"] = cli_rule["patterns"]
                        else:
                            rules["cli_indicators"] = cli_rule
                    
                    if "EXPERT" in heuristics:
                        expert_rule = heuristics["EXPERT"]
                        if isinstance(expert_rule, dict) and "patterns" in expert_rule:
                            rules["expert_indicators"] = expert_rule["patterns"]
                        else:
                            rules["expert_indicators"] = expert_rule
                    
                    if "MULTI_AGENT" in heuristics:
                        multi_rule = heuristics["MULTI_AGENT"]
                        if isinstance(multi_rule, dict) and "patterns" in multi_rule:
                            rules["multi_agent_indicators"] = multi_rule["patterns"]
                        else:
                            rules["multi_agent_indicators"] = multi_rule
            
            # Extract route_categories detection_patterns (alternative location)
            if "route_categories" in skill_data:
                categories = skill_data["route_categories"]
                
                if "REJECT" in categories and "detection_patterns" in categories["REJECT"]:
                    rules["dangerous_patterns"] = categories["REJECT"]["detection_patterns"]
            
            logger.info(f"✅ Loaded Guard rules from SKILL.md")
            return rules
            
        except Exception as e:
            logger.error(f"❌ Failed to load SKILL.md rules: {e}")
            logger.info("   Using default rules")
            return self.DEFAULT_RULES.copy()
    
    def _apply_settings_overrides(self, rules: dict[str, list[str]]) -> dict[str, list[str]]:
        """Apply rule overrides from config/settings.py."""
        try:
            from config.settings import settings
            
            # Check if settings has guard_rules_overrides
            if hasattr(settings, 'agent') and hasattr(settings.agent, 'guard_rules_overrides'):
                overrides = settings.agent.guard_rules_overrides
                if isinstance(overrides, dict):
                    for key, patterns in overrides.items():
                        if isinstance(patterns, list):
                            rules[key] = patterns
                            logger.info(f"✅ Applied settings override for {key}: {len(patterns)} patterns")
        
        except Exception as e:
            logger.debug(f"⚠️ No settings overrides applied: {e}")
        
        return rules
    
    def _apply_env_overrides(self, rules: dict[str, list[str]]) -> dict[str, list[str]]:
        """Apply rule overrides from environment variables."""
        import os
        
        # Check for OLAV_GUARD_RULES_FILE environment variable
        custom_rules_file = os.getenv("OLAV_GUARD_RULES_FILE")
        if custom_rules_file:
            try:
                custom_path = Path(custom_rules_file)
                if custom_path.exists():
                    with open(custom_path, 'r', encoding='utf-8') as f:
                        custom_rules = yaml.safe_load(f)
                    
                    if isinstance(custom_rules, dict):
                        rules.update(custom_rules)
                        logger.info(f"✅ Applied environment override from {custom_rules_file}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load custom rules from {custom_rules_file}: {e}")
        
        return rules
    
    def get_patterns_for_route(self, route_type: str) -> list[str]:
        """Get regex patterns for a specific route type.
        
        Args:
            route_type: One of SIMPLE, CLI, EXPERT, MULTI_AGENT, REJECT
            
        Returns:
            List of regex patterns for this route type
        """
        route_map = {
            "SIMPLE": "simple_indicators",
            "CLI": "cli_indicators",
            "EXPERT": "expert_indicators",
            "MULTI_AGENT": "multi_agent_indicators",
            "REJECT": "dangerous_patterns",
        }
        
        key = route_map.get(route_type, f"{route_type.lower()}_indicators")
        return self.rules.get(key, [])
    
    def get_realtime_indicators(self) -> list[str]:
        """🔥 Phase 2.3: Get realtime keyword indicators."""
        return self.rules.get("realtime_indicators", [])
    
    def get_force_live_scenarios(self) -> list[dict]:
        """🔥 Phase 2.3: Get force live scenarios."""
        return self.rules.get("force_live_scenarios", [])
    
    def get_prefer_structured_commands(self) -> list[str]:
        """🔥 Phase 2.4: Get commands that prefer TextFSM parsing."""
        return self.rules.get("prefer_structured_commands", [])
    
    def get_force_raw_scenarios(self) -> list[dict]:
        """🔥 Phase 2.4: Get scenarios that force raw output."""
        return self.rules.get("force_raw_scenarios", [])
    
    def reload(self) -> None:
        """Reload rules from SKILL.md (useful for hot-reload)."""
        self._rules = None
        logger.info("🔄 Guard rules reloaded")


# Singleton instance
_loader = None


def get_rules_loader() -> GuardRulesLoader:
    """Get singleton rules loader instance."""
    global _loader
    if _loader is None:
        _loader = GuardRulesLoader()
    return _loader
