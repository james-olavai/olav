"""
Guard Router - Query Classification and Fast Routing

Purpose:
  Fast query classification system (4-stage pipeline: dangerous → cache → heuristic → LLM)
  Reduces latency from 12s to 2s for simple queries (~80% improvement)

Architecture:
  Stage 1: Dangerous pattern detection (regex, <10ms)
  Stage 2: Semantic cache lookup (DuckDB, 10-50ms, 45% hit rate)
  Stage 3: Fast heuristic classification (regex, <5ms, 30% match)
  Stage 4: LLM classification (1-2s, fallback for <0.85 confidence)

Design Principle:
  ✅ Skill-Centric: All rules loaded from .olav/skills/olav-guard/SKILL.md
  ✅ No Hardcoded: Override chain: SKILL.md → config/settings.py → .env → .olav/settings.json
  ✅ User-Configurable: Users can customize rules in .olav/settings.json or via environment

Module Decomposition (Phase 2.2):
  - security_classifier: Pattern-based dangerous detection + heuristic classification
  - cache_manager: DuckDB semantic cache operations
  - llm_router: LLM-based classification fallback
  - execution_dispatcher: Route-specific execution handlers

Version: 2.0.0 (Modularized)
Status: Phase 2.2 Implementation
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from config.settings import settings
from olav.core.guard_rules_loader import get_rules_loader

from .cache_manager import CacheManager
from .execution_dispatcher import ExecutionDispatcher
from .llm_router import LLMRouter
from .security_classifier import SecurityClassifier

logger = logging.getLogger(__name__)


class RouteCode(Enum):
    """Query routing categories."""
    
    REJECT = "REJECT"                 # Dangerous/unsafe queries
    SIMPLE = "SIMPLE"                 # Simple database queries (1-2 tables)
    CLI = "CLI"                       # Real-time device CLI data
    EXPERT = "EXPERT"                 # Complex analytics/joins/aggregations
    MULTI_AGENT = "MULTI_AGENT"       # Cross-system comparison (NetBox vs DB, etc.)
    UNKNOWN = "UNKNOWN"               # Ambiguous - requires Orchestrator planning


@dataclass
class RouteDecision:
    """Guard routing decision with confidence score."""
    
    code: RouteCode
    confidence: float              # 0.0-1.0 confidence score
    reasoning: str                 # Why this classification
    cache_hit: bool = False        # Was this a cache hit?
    risk_level: str = "safe"       # safe | warning | dangerous
    detected_intent: str = ""      # Keyword or pattern that triggered classification
    
    # 🔥 Phase 2.5: CLI Agent extensions
    use_textfsm: bool = True       # Whether to use TextFSM parsing (default: True)
    cache_bypass: bool = False     # Whether to bypass all caches (for realtime queries)
    textfsm_reasoning: str = ""    # Explanation for TextFSM decision
    
    # ✅ Phase 3.1: CSV Export support (Restore original design)
    export_requested: bool = False # Whether user requested data export
    export_format: str = "csv"     # Export format (csv, json, markdown, etc.)
    
    def should_direct_route(self) -> bool:
        """Check if confidence is high enough for direct routing."""
        return self.confidence >= settings.agent.guard_confidence_threshold


class QueryGuard:
    """Query classification guard with semantic caching.
    
    Core Responsibilities:
    1. Dangerous command detection (rule-based, <10ms)
    2. Semantic cache lookup (DuckDB, 10-50ms, ~45% hit rate)
    3. Fast heuristic classification (regex, <5ms, ~30% match)
    4. LLM classification (1-2s fallback)
    
    Design Principles:
    ✅ Skill-Centric: Rules loaded from SKILL.md, not hardcoded
    ✅ No Hardcoded Config: Override chain (SKILL.md → settings → .env)
    ✅ User-Friendly: Can customize rules via .olav/settings.json
    
    Module Dependencies (Phase 2.2 Decomposition):
    - security_classifier: Dangerous detection + heuristic classification
    - cache_manager: DuckDB cache operations
    - llm_router: LLM-based classification
    - execution_dispatcher: Route-specific execution
    """
    
    def __init__(self):
        """Initialize Guard with modular components."""
        
        # Initialize rules loader (SKILL.md loading)
        rules_loader = get_rules_loader()
        rules_data = {
            "dangerous_patterns": rules_loader.get_patterns_for_route("REJECT"),
            "simple_indicators": rules_loader.get_patterns_for_route("SIMPLE"),
            "cli_indicators": rules_loader.get_patterns_for_route("CLI"),
            "expert_indicators": rules_loader.get_patterns_for_route("EXPERT"),
            "multi_agent_indicators": rules_loader.get_patterns_for_route("MULTI_AGENT"),
            "realtime_indicators": rules_loader.get_realtime_indicators(),
            "force_live_scenarios": rules_loader.get_force_live_scenarios(),
            "prefer_structured_commands": rules_loader.get_prefer_structured_commands(),
            "force_raw_scenarios": rules_loader.get_force_raw_scenarios(),
        }
        
        logger.info(f"✅ Guard rules loaded from SKILL.md:")
        logger.info(f"   - Dangerous patterns: {len(rules_data['dangerous_patterns'])}")
        logger.info(f"   - SIMPLE indicators: {len(rules_data['simple_indicators'])}")
        logger.info(f"   - CLI indicators: {len(rules_data['cli_indicators'])}")
        logger.info(f"   - EXPERT indicators: {len(rules_data['expert_indicators'])}")
        logger.info(f"   - MULTI_AGENT indicators: {len(rules_data['multi_agent_indicators'])}")
        logger.info(f"   - Realtime indicators: {len(rules_data['realtime_indicators'])}")
        logger.info(f"   - Prefer structured commands: {len(rules_data['prefer_structured_commands'])}")
        
        # Initialize modular components
        self.security_classifier = SecurityClassifier(rules_data)
        self.cache_manager = CacheManager()
        self.llm_router = LLMRouter()
        self.executor = ExecutionDispatcher()
        
        # Configuration from settings.py
        self.enabled = settings.agent.enable_guard_routing
        self.confidence_threshold = settings.agent.guard_confidence_threshold
        
        logger.info(f"🛡️  Guard initialized: enabled={self.enabled}, "
                    f"threshold={self.confidence_threshold}")
    
    def classify(self, query: str, user_id: str | None = None) -> RouteDecision:
        """Classify query through multi-stage pipeline.
        
        Stage 0: Dangerous pattern detection (rule-based, <10ms)
        Stage 1: Semantic cache lookup (DuckDB, 10-50ms, ~45% hit rate)
        Stage 2: Fast heuristic classification (regex, <5ms, ~30% match)
        Stage 3: LLM classification (1-2s fallback for <0.75 confidence)
        
        Args:
            query: User's natural language query
            user_id: User ID for logging (optional)
            
        Returns:
            RouteDecision with routing category, confidence, and reasoning
        """
        
        if not self.enabled:
            logger.debug("🔓 Guard is disabled, returning UNKNOWN")
            export_requested, export_format = self.security_classifier.detect_export_request(query)
            return RouteDecision(
                code=RouteCode.UNKNOWN,
                confidence=0.0,
                reasoning="Guard routing is disabled",
                risk_level="safe",
                export_requested=export_requested,
                export_format=export_format,
            )
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 0: Realtime Keyword Detection (🔥 Phase 2.3, Highest Priority)
        # ═══════════════════════════════════════════════════════════════
        if self.security_classifier.detect_realtime_keywords(query):
            logger.info(f"🔥 Realtime keyword detected: {query[:60]}...")
            export_requested, export_format = self.security_classifier.detect_export_request(query)
            return RouteDecision(
                code=RouteCode.CLI,
                confidence=0.95,
                reasoning="Realtime data request detected - direct CLI execution",
                cache_bypass=True,  # 🔥 Bypass all caches
                use_textfsm=self.security_classifier.should_use_textfsm(query),
                textfsm_reasoning=self.security_classifier.explain_textfsm_choice(query),
                detected_intent="realtime_request",
                risk_level="safe",
                export_requested=export_requested,
                export_format=export_format,
            )
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 1: Dangerous Pattern Detection (Rule-based, <10ms)
        # ═══════════════════════════════════════════════════════════════
        if self.security_classifier.is_dangerous(query):
            logger.warning(f"🚫 Dangerous pattern detected: {query[:60]}...")
            export_requested, export_format = self.security_classifier.detect_export_request(query)
            return RouteDecision(
                code=RouteCode.REJECT,
                confidence=0.95,
                reasoning="Dangerous operation detected - query blocked",
                risk_level="dangerous",
                detected_intent="dangerous_operation",
                export_requested=export_requested,
                export_format=export_format,
            )
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 2: Semantic Cache Lookup (DuckDB, 10-50ms)
        # ═══════════════════════════════════════════════════════════════
        cache_result = self.cache_manager.check_cache(query)
        if cache_result:
            logger.info(f"⚡ Cache hit (Stage 2): {query[:60]}... → {cache_result['route_code']} "
                        f"({cache_result['confidence']:.2f})")
            export_requested, export_format = self.security_classifier.detect_export_request(query)
            return RouteDecision(
                code=RouteCode(cache_result['route_code']),
                confidence=cache_result['confidence'],
                reasoning=cache_result['reasoning'],
                cache_hit=True,
                risk_level=cache_result['risk_level'],
                detected_intent=cache_result['detected_intent'],
                export_requested=export_requested,
                export_format=export_format,
            )
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 3: Fast Heuristic Classification (Regex, <5ms)
        # ═══════════════════════════════════════════════════════════════
        heuristic_result = self.security_classifier.fast_heuristic_check(query)
        if heuristic_result:
            route_code, confidence, reasoning, intent = heuristic_result
            if confidence >= self.confidence_threshold:
                logger.info(f"🎯 Heuristic match (Stage 3): {query[:60]}... → {route_code} "
                            f"({confidence:.2f})")
                decision = {
                    "code": route_code,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "risk_level": "safe",
                    "detected_intent": intent
                }
                self.cache_manager.cache_decision(query, decision)
                export_requested, export_format = self.security_classifier.detect_export_request(query)
                return RouteDecision(
                    code=RouteCode(route_code),
                    confidence=confidence,
                    reasoning=reasoning,
                    risk_level="safe",
                    detected_intent=intent,
                    export_requested=export_requested,
                    export_format=export_format,
                )
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 4: LLM Classification (1-2s, fallback)
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"🤖 LLM classification (Stage 4): {query[:60]}...")
        llm_result = self.llm_router.classify(query)
        
        # 🔥 Phase 2.4: Add TextFSM recommendation for CLI routes
        if llm_result['route_code'] == RouteCode.CLI.value:
            llm_result['use_textfsm'] = self.security_classifier.should_use_textfsm(query)
            llm_result['textfsm_reasoning'] = self.security_classifier.explain_textfsm_choice(query)
        
        self.cache_manager.cache_decision(query, llm_result)
        
        # ✅ Phase 3.1: Detect export request
        export_requested, export_format = self.security_classifier.detect_export_request(query)
        
        return RouteDecision(
            code=RouteCode(llm_result['route_code']),
            confidence=llm_result['confidence'],
            reasoning=llm_result['reasoning'],
            risk_level=llm_result.get('risk_level', 'safe'),
            detected_intent=llm_result.get('detected_intent', ''),
            use_textfsm=llm_result.get('use_textfsm', True),
            textfsm_reasoning=llm_result.get('textfsm_reasoning', ''),
            export_requested=export_requested,
            export_format=export_format,
        )
    
    def route_and_execute(
        self,
        query: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Route and execute query based on Guard classification.
        
        Args:
            query: User's natural language query
            user_id: User ID for feature flags
        
        Returns:
            Dict with status, final_answer, error_message
        """
        # Classify query
        decision = self.classify(query, user_id=user_id)
        
        # Convert RouteDecision to dict for executor
        decision_dict = {
            "route_code": decision.code.value,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "risk_level": decision.risk_level,
            "detected_intent": decision.detected_intent,
            "use_textfsm": decision.use_textfsm,
            "cache_bypass": decision.cache_bypass,
            "textfsm_reasoning": decision.textfsm_reasoning,
            "export_requested": decision.export_requested,  # ✅ Phase 3.1
            "export_format": decision.export_format,        # ✅ Phase 3.1
        }
        
        # Execute via dispatcher
        return self.executor.route_and_execute(
            query=query,
            decision=decision_dict,
            confidence_threshold=settings.agent.guard_confidence_threshold,
            user_id=user_id
        )
    
    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring."""
        return self.cache_manager.get_stats()


# Singleton instance (optional, for convenience)
_guard_instance: Optional[QueryGuard] = None


def get_guard() -> QueryGuard:
    """Get or create Guard singleton instance.
    
    Usage:
        guard = get_guard()
        decision = guard.classify("show all devices")
    """
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = QueryGuard()
    return _guard_instance


# ═══════════════════════════════════════════════════════════════
# Public API Exports (Backward Compatibility - Phase 2.2)
# ═══════════════════════════════════════════════════════════════

__all__ = [
    "RouteCode",
    "RouteDecision",
    "QueryGuard",
    "get_guard",
]
