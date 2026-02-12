"""LLM Router: LLM-based classification for Guard decisions.

Responsibilities:
1. LLM-based fallback classification (Stage 4, 1-2s)
2. Load Guard SKILL.md prompt (Skill-Centric Design)
3. Parse LLM response into structured RouteDecision
4. Fallback prompt generation

Time budget: 1000-2000ms
Accuracy: ~95% for router queries
Temperature: 0.1 (low for consistency)
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)


class LLMRouter:
    """LLM-based classification router for Guard decisions.
    
    Uses Guard SKILL.md prompt or fallback for classification
    when heuristics and cache don't match.
    """
    
    def __init__(self):
        """Initialize LLM router with low temperature for consistency."""
        # Initialize LLM (low temperature for consistency)
        self.llm = LLMFactory.get_chat_model(temperature=0.1)
        logger.info("✅ Guard LLM initialized")
    
    def classify(self, query: str) -> dict[str, Any]:
        """Stage 4: LLM-based classification (fallback, 1-2s).
        
        Time budget: 1000-2000ms
        Accuracy: ~95% for router queries
        
        Uses Guard SKILL.md prompt or fallback inline prompt.
        
        Args:
            query: User query to classify
        
        Returns:
            Dict with route decision:
            {
                "route_code": str (SIMPLE|CLI|EXPERT|etc),
                "confidence": float,
                "reasoning": str,
                "risk_level": str (safe|dangerous|unknown),
                "detected_intent": str
            }
        """
        # Try to load Guard SKILL.md prompt
        system_prompt = self._load_guard_prompt()
        
        # Prepare LLM input
        user_message = f"{system_prompt}\n\nQuery to classify: {query}"
        
        try:
            response = self.llm.invoke([HumanMessage(content=user_message)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse LLM response (expecting JSON or structured format)
            decision = self._parse_response(response_text, query)
            logger.debug(f"🤖 LLM decision: {query[:60]}... → {decision.get('route_code')} "
                        f"({decision.get('confidence'):.2f})")
            return decision
            
        except Exception as e:
            logger.error(f"❌ LLM classification error: {e}")
            # Fallback to UNKNOWN for safe degradation
            return {
                "route_code": "UNKNOWN",
                "confidence": 0.30,
                "reasoning": "LLM classification failed, deferring to Orchestrator",
                "risk_level": "safe",
                "detected_intent": "llm_error"
            }
    
    def _load_guard_prompt(self) -> str:
        """Load Guard classification prompt from SKILL.md.
        
        Implements Skill-Centric Design:
        - Rules/prompts defined in .olav/skills/olav-guard/SKILL.md
        - No hardcoded prompts (fallback only)
        - Override via settings.json or .env
        
        Returns:
            System prompt for LLM classification
        """
        skill_path = Path(".olav") / "skills" / "guard" / "SKILL.md"
        
        try:
            if skill_path.exists():
                with open(skill_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    # Extract system prompt from markdown
                    if '---' in content:
                        parts = content.split('---')
                        if len(parts) >= 3:
                            # Skip frontmatter, extract content
                            body = parts[2].strip()
                            # Find classification_system_prompt section
                            if 'classification_system_prompt:' in body:
                                start = body.find('classification_system_prompt:')
                                section = body[start:].split('\n', 1)[1]
                                # Extract just the prompt text (between pipes)
                                if '|' in section:
                                    prompt = section.split('|', 1)[1].strip()
                                    # Remove trailing metadata
                                    prompt = prompt.split('\n\nroute_categories:')[0]
                                    return prompt
            
            # If SKILL.md not found or parsing failed, use fallback
            return self._get_fallback_prompt()
            
        except Exception as e:
            logger.debug(f"⚠️  Failed to load Guard SKILL.md: {e}. Using fallback prompt.")
            return self._get_fallback_prompt()
    
    def _get_fallback_prompt(self) -> str:
        """Fallback classification prompt.
        
        Used when SKILL.md is unavailable or cannot be parsed.
        """
        return """Classify this network query into ONE of these categories:

REJECT - Dangerous/unsafe operations (delete all, shutdown, etc.)
SIMPLE - Count/list queries from single table (count devices, list interfaces)
CLI - Real-time device data (show commands, current status)
EXPERT - Complex analysis (joins, trends, diagnose, optimize)
MULTI_AGENT - Cross-system comparison (NetBox vs DB, snapshot vs live)
UNKNOWN - Ambiguous query requiring planning

Respond in JSON:
{
  "route_type": "<CATEGORY>",
  "confidence": <0.0-1.0>,
  "reasoning": "<explain choice>"
}"""
    
    def _parse_response(self, response: str, query: str = "") -> dict[str, Any]:
        """Parse LLM response into RouteDecision.
        
        Expects JSON or structured format:
        {
          "route_type": "SIMPLE",
          "confidence": 0.90,
          "reasoning": "..."
        }
        
        Args:
            response: LLM response text
            query: Original query (for fallback)
        
        Returns:
            Parsed decision dict
        """
        try:
            # Try to extract JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                
                route_str = data.get('route_type', 'UNKNOWN').upper().strip()
                confidence = float(data.get('confidence', 0.5))
                reasoning = data.get('reasoning', 'LLM classification')
                
                # Validate route code
                valid_routes = ["REJECT", "SIMPLE", "CLI", "EXPERT", "MULTI_AGENT", "UNKNOWN"]
                if route_str not in valid_routes:
                    logger.warning(f"⚠️  Invalid route code from LLM: {route_str}")
                    route_str = "UNKNOWN"
                    confidence = min(confidence, 0.5)
                
                # Clamp confidence
                confidence = max(0.0, min(1.0, confidence))
                
                return {
                    "route_code": route_str,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "risk_level": "safe",
                    "detected_intent": "llm_classification"
                }
        except json.JSONDecodeError:
            logger.debug(f"⚠️  Failed to parse LLM JSON response")
        except Exception as e:
            logger.debug(f"⚠️  Error parsing LLM response: {e}")
        
        # Fallback: default to UNKNOWN
        return {
            "route_code": "UNKNOWN",
            "confidence": 0.40,
            "reasoning": "Could not parse LLM response, deferring to Orchestrator",
            "risk_level": "safe",
            "detected_intent": "parse_error"
        }
