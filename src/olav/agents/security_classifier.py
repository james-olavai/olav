"""🛡️ Security Classifier: Dangerous detection + Heuristic classification.

Responsibilities:
1. Pattern-based dangerous operation detection (<10ms)
2. Real-time keyword detection (Stage 0)
3. Fast heuristic classification (regex, <5ms, ~30% match)
4. TextFSM scheduling decision (structured vs raw output)

Design Principles:
✅ Skill-Centric: Rules loaded from SKILL.md, not hardcoded
✅ Ultra-Conservative: Default to database queries (SIMPLE) for safety
✅ Performance-Optimized: All operations <10ms except fallback

Typical time budget:
- _is_dangerous: <10ms
- _detect_realtime_keywords: <5ms
- _fast_heuristic_check: <5ms
- _should_use_textfsm: <2ms
"""

import logging
import re
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


class SecurityClassifier:
    """Pattern-based security and heuristic classification.
    
    Loaded from Guard initialization, provides classification methods
    without needing full LLM inference.
    """
    
    def __init__(self, rules_data: dict):
        """Initialize with rules loaded from SKILL.md.
        
        Args:
            rules_data: Dictionary containing:
                - dangerous_patterns: List of regex patterns for dangerous ops
                - simple_indicators: List of patterns for SIMPLE queries
                - cli_indicators: List of patterns for CLI queries
                - expert_indicators: List of patterns for EXPERT queries
                - multi_agent_indicators: List of patterns for MULTI_AGENT
                - realtime_indicators: List of keywords for real-time detection
                - force_live_scenarios: List of pattern-based force-live rules
                - prefer_structured_commands: List of commands preferring TextFSM
                - force_raw_scenarios: List of pattern-based force-raw rules
        """
        self.dangerous_patterns = rules_data.get("dangerous_patterns", [])
        self.simple_indicators = rules_data.get("simple_indicators", [])
        self.cli_indicators = rules_data.get("cli_indicators", [])
        self.expert_indicators = rules_data.get("expert_indicators", [])
        self.multi_agent_indicators = rules_data.get("multi_agent_indicators", [])
        self.realtime_indicators = rules_data.get("realtime_indicators", [])
        self.force_live_scenarios = rules_data.get("force_live_scenarios", [])
        self.prefer_structured_commands = rules_data.get("prefer_structured_commands", [])
        self.force_raw_scenarios = rules_data.get("force_raw_scenarios", [])
        self.multi_agent_detection_enabled = getattr(settings, "agent", {}).enable_multi_agent_detection
    
    def is_dangerous(self, query: str) -> bool:
        """Stage 1: Check if query matches dangerous patterns.
        
        Time budget: <10ms
        Accuracy: 100% for matched patterns
        
        Rules loaded from: .olav/skills/olav-guard/SKILL.md (Skill-Centric Design)
        Override via: config/settings.py or .olav/settings.json or .env
        """
        query_lower = query.lower()
        
        for pattern in self.dangerous_patterns:
            try:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    return True
            except re.error as e:
                logger.debug(f"⚠️  Invalid regex pattern: {pattern}: {e}")
        
        return False
    
    def detect_realtime_keywords(self, query: str) -> bool:
        """🔥 Phase 2.3: Detect realtime/current/now keywords.
        
        Priority: Highest (Stage 0 - before dangerous check)
        Time budget: <5ms
        Accuracy: 95%+ for keyword detection
        
        Returns:
            True if realtime keywords detected or force_live scenario matched
        """
        query_lower = query.lower()
        
        # Priority 1: Check realtime keyword indicators
        for keyword in self.realtime_indicators:
            keyword_lower = keyword.lower()
            
            # For Chinese characters: direct substring match (no word boundaries)
            if any(ord(char) > 127 for char in keyword):
                if keyword_lower in query_lower:
                    logger.debug(f"✅ Realtime keyword matched (Chinese): '{keyword}'")
                    return True
            else:
                # For English/ASCII: use word boundary matching
                if re.search(rf"\b{re.escape(keyword_lower)}\b", query_lower):
                    logger.debug(f"✅ Realtime keyword matched (English): '{keyword}'")
                    return True
        
        # Priority 2: Check force_live_scenarios (pattern-based)
        for scenario in self.force_live_scenarios:
            pattern = scenario.get("pattern", "")
            if pattern and re.search(pattern, query_lower):
                reason = scenario.get("reason", "Force live scenario")
                logger.debug(f"✅ Force live scenario matched: {reason}")
                return True
        
        return False
    
    def should_use_textfsm(self, query: str) -> bool:
        """🔥 Phase 2.4: Determine if TextFSM parsing should be used.
        
        Priority:
        P1: User explicitly requests raw → False
        P2: Command in prefer_structured list → True
        P3: Default from settings → settings.execution.use_textfsm
        
        Returns:
            True if TextFSM should be used, False for raw output
        """
        query_lower = query.lower()
        
        # P1: Check force_raw_scenarios (user override)
        for scenario in self.force_raw_scenarios:
            pattern = scenario.get("pattern", "")
            if pattern and re.search(pattern, query_lower):
                reason = scenario.get("reason", "User requested raw format")
                logger.debug(f"🔄 Force raw: {reason}")
                return False
        
        # P2: Check prefer_structured_commands
        for cmd in self.prefer_structured_commands:
            if cmd.lower() in query_lower:
                logger.debug(f"✅ Prefer structured: '{cmd}' found in query")
                return True
        
        # P3: Default from settings
        default = settings.execution.use_textfsm
        logger.debug(f"⚙️ Using default TextFSM setting: {default}")
        return default
    
    def explain_textfsm_choice(self, query: str) -> str:
        """Generate explanation for TextFSM decision.
        
        Returns:
            Human-readable explanation string
        """
        query_lower = query.lower()
        
        # Check force_raw
        for scenario in self.force_raw_scenarios:
            pattern = scenario.get("pattern", "")
            if pattern and re.search(pattern, query_lower):
                return scenario.get("reason", "User requested raw format")
        
        # Check prefer_structured
        for cmd in self.prefer_structured_commands:
            if cmd.lower() in query_lower:
                return f"Command '{cmd}' has TextFSM template available"
        
        # Default
        if settings.execution.use_textfsm:
            return "Default TextFSM parsing enabled"
        else:
            return "TextFSM disabled by configuration"
    
    def fast_heuristic_check(self, query: str) -> Optional[tuple[str, float, str, str]]:
        """Stage 3: Fast regex-based heuristic classification.
        
        Time budget: <5ms
        Expected match rate: ~30%
        Matching order: SIMPLE → CLI → MULTI_AGENT → EXPERT
        
        🔥 Ultra-Conservative Strategy:
        - Default to SIMPLE for database queries unless explicitly requesting real-time CLI
        - Any "show" query without real-time keywords → SIMPLE (Database)
        - Only route to CLI if real-time keywords present
        
        Returns:
            Tuple of (route_code, confidence, reasoning, detected_intent) if confidence >= threshold
            None otherwise (fallback to LLM)
        """
        query_lower = query.lower()
        
        # 🔥 Safety Check: If query contains "show" but NO real-time keywords → SIMPLE (Database)
        realtime_keywords = ["实时", "real-time", "live", "当前", "立即", "现在", "最新", "即刻", "马上", "正在", "目前"]
        has_show = re.search(r"\bshow\b", query_lower)
        has_realtime = any(kw.lower() in query_lower for kw in realtime_keywords)
        
        if has_show and not has_realtime:
            logger.debug(f"✅ Safety check: 'show' without real-time keyword → SIMPLE")
            return ("SIMPLE", 0.92, "Query contains 'show' without real-time keywords → defaults to database lookup", "default_simple_show")
        
        # Priority 1: SIMPLE queries (most common, ~65%)
        # Rules loaded from: .olav/skills/olav-guard/SKILL.md
        for pattern in self.simple_indicators:
            try:
                if re.search(pattern, query, re.IGNORECASE):
                    return ("SIMPLE", 0.90, "Simple query pattern detected (heuristic)", "simple_count_list")
            except re.error as e:
                logger.debug(f"⚠️  Invalid SIMPLE pattern: {pattern}: {e}")
        
        # Priority 2: CLI queries (real-time data, ~15%)
        # 🔥 ONLY matches if explicit real-time keywords present
        # Rules loaded from: .olav/skills/olav-guard/SKILL.md
        for pattern in self.cli_indicators:
            try:
                if re.search(pattern, query, re.IGNORECASE):
                    return ("CLI", 0.88, "CLI real-time data pattern detected (heuristic)", "cli_realtime_data")
            except re.error as e:
                logger.debug(f"⚠️  Invalid CLI pattern: {pattern}: {e}")
        
        # Priority 3: MULTI_AGENT queries (BEFORE EXPERT - cross-system priority)
        # Rules loaded from: .olav/skills/olav-guard/SKILL.md
        if self.multi_agent_detection_enabled:
            for pattern in self.multi_agent_indicators:
                try:
                    if re.search(pattern, query, re.IGNORECASE):
                        return ("MULTI_AGENT", 0.88, "Multi-agent cross-system comparison detected (heuristic)", "cross_system_validation")
                except re.error as e:
                    logger.debug(f"⚠️  Invalid MULTI_AGENT pattern: {pattern}: {e}")
        
        # Priority 4: EXPERT queries (complex analysis, ~13%)
        # Rules loaded from: .olav/skills/olav-guard/SKILL.md
        for pattern in self.expert_indicators:
            try:
                if re.search(pattern, query, re.IGNORECASE):
                    return ("EXPERT", 0.87, "Expert analytics pattern detected (heuristic)", "complex_analytics")
            except re.error as e:
                logger.debug(f"⚠️  Invalid EXPERT pattern: {pattern}: {e}")
        
        return None
