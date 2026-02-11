"""Query Complexity & Expert Routing - Confidence Scoring (v0.11.4+)

Instead of hardcoded keyword matching, use LLM-based confidence scoring to
determine if a query needs Expert-level analysis.

Design:
1. Score query complexity: 0.0 (simple) → 1.0 (complex)
2. Simple queries (score < 0.3): Route to Query Agent
3. Complex queries (score >= 0.3): Route to Expert Agent
4. Query Agent can self-escalate if it needs help

Benefits:
- Flexible, not keyword-dependent
- Handles edge cases gracefully
- Query Agent has autonomy to request Expert help
- Two-layer safety net: initial scoring + runtime escalation
"""

import logging
from typing import Any
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


class QueryComplexityScorer:
    """Score query complexity to determine routing.
    
    Scoring criteria:
    - 0.0-0.2: Simple (count, list, filter on 1-2 fields)
    - 0.2-0.4: Medium (aggregation, 2+ conditions, time-ranges)
    - 0.4-0.7: Complex (analysis, trends, predictions)
    - 0.7-1.0: Expert-level (RCA, design, audit, recommendations)
    """
    
    @staticmethod
    def score(user_query: str, llm: Any) -> dict[str, Any]:
        """Score query using LLM.
        
        Args:
            user_query: User's natural language query
            llm: LLM instance for scoring
            
        Returns:
            Dictionary with:
            - score: float [0.0, 1.0] - complexity score
            - category: str - one of 'simple', 'medium', 'complex', 'expert'
            - reasoning: str - why this score
            - needs_expert: bool - True if score >= 0.3
        """
        
        logger.debug(f"  0️⃣ Scoring query complexity...")
        
        # Scoring prompt
        scoring_prompt = f"""Analyze this network query and score its complexity.

Query: "{user_query}"

Score Complexity (0.0 = simple, 1.0 = expert-only):
- 0.0-0.2: Basic facts (count devices, list interfaces, filter by role)
- 0.2-0.4: Aggregations (stats, grouping, multi-condition filters)
- 0.4-0.7: Analysis (trends, correlations, predictions, optimization)
- 0.7-1.0: Expert diagnosis (RCA, design, compliance audit, recommendations)

Respond in this exact format:
SCORE: [0.0-1.0]
CATEGORY: [simple|medium|complex|expert]
REASONING: [one sentence explanation]"""
        
        try:
            response = llm.invoke([HumanMessage(content=scoring_prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse response
            score = 0.5  # default
            category = "medium"
            reasoning = "Unable to parse"
            
            lines = response_text.strip().split('\n')
            for line in lines:
                if line.startswith("SCORE:"):
                    try:
                        score = float(line.split(":", 1)[1].strip())
                        score = max(0.0, min(1.0, score))  # Clamp to [0, 1]
                    except ValueError:
                        pass
                elif line.startswith("CATEGORY:"):
                    category = line.split(":", 1)[1].strip().lower()
                elif line.startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()
            
            needs_expert = score >= 0.3
            
            logger.debug(f"    ✓ Score: {score:.2f} ({category})")
            if needs_expert:
                logger.info(f"  ⚡ High complexity detected (score={score:.2f}), will route to Expert")
            
            return {
                "score": score,
                "category": category,
                "reasoning": reasoning,
                "needs_expert": needs_expert,
            }
            
        except Exception as e:
            logger.warning(f"    ⚠ Scoring failed: {e}")
            # Default to conservative: if scoring fails, prefer Query Agent
            return {
                "score": 0.2,  # Conservative default
                "category": "simple",
                "reasoning": "Scoring unavailable, defaulting to Query Agent",
                "needs_expert": False,
            }


class QueryEscalationMarker:
    """Query Agent can return this to request Expert escalation.
    
    Format: <escalate_to_expert>reason</escalate_to_expert>
    
    This allows Query Agent to self-assess and request help when
    needed, without pre-routing decisions.
    """
    
    PATTERN = r'<escalate_to_expert>(.*?)</escalate_to_expert>'
    
    @staticmethod
    def check(response_text: str) -> tuple[bool, str]:
        """Check if response contains escalation request.
        
        Args:
            response_text: Query Agent's response text
            
        Returns:
            (has_escalation_marker, reason)
        """
        import re
        match = re.search(QueryEscalationMarker.PATTERN, response_text, re.DOTALL)
        
        if match:
            reason = match.group(1).strip()
            logger.info(f"  🚀 Query Agent requested escalation: {reason[:50]}...")
            return True, reason
        
        return False, ""


# Usage in Orchestrator:
#
# 1. INITIAL ROUTING (before Query Agent):
#    score = QueryComplexityScorer.score(user_query, llm)
#    if score['needs_expert']:
#        route_to_expert()
#    else:
#        route_to_query()
#
# 2. RUNTIME ESCALATION (after Query Agent responds):
#    have_marker, reason = QueryEscalationMarker.check(query_response)
#    if have_marker:
#        route_to_expert_with_context(query_response, reason)


class SchemaDataValidator:
    """Check if database schema has sufficient data for analysis.
    
    Purpose: Prevent Expert routing when database lacks required data.
    
    Expert-level analysis needs:
    - For RCA: interfaces, errors, logs, topology
    - For predictions: historical trends, metrics
    - For recommendations: configs, performance data
    
    Simple inventory data (devices table only) → Not suitable for Expert analysis
    """
    
    @staticmethod
    def has_sufficient_data_for_expert(user_query: str, llm: Any) -> dict[str, Any]:
        """Check if database has sufficient data for expert analysis.
        
        Args:
            user_query: User's query
            llm: LLM instance
            
        Returns:
            Dictionary with:
            - has_data: bool - True if sufficient data exists
            - available_tables: list - tables in database
            - missing_data: str - what data is missing for analysis
            - reason: str - why analysis is possible/impossible
            - recommendation: str - suggested next step
        """
        
        logger.debug(f"  📊 Validating schema for expert analysis...")
        
        try:
            # For now, assume we have minimal schema (devices table)
            # Expert will request more data via <need_cli_data> marker if needed
            available_tables = ["devices"]  # Known minimal set
            
            # Check if query is asking for things that clearly need CLI
            cli_keywords = ["ospf", "bgp", "interface", "errors", "status", "neighbor", "adjacency"]
            needs_cli = any(keyword in user_query.lower() for keyword in cli_keywords)
            
            if needs_cli:
                logger.debug(f"    Query likely needs CLI data ({user_query[:50]}...)")
                return {
                    "has_data": True,  # Optimistic - let Expert try and request CLI if needed
                    "available_tables": available_tables,
                    "missing_data": [],
                    "reason": "Query may require CLI data - Expert will request if needed",
                    "recommendation": "Proceed to Expert, Expert will request CLI data",
                }
            else:
                logger.debug(f"    Query answerable from inventory")
                return {
                    "has_data": True,
                    "available_tables": available_tables,
                    "missing_data": [],
                    "reason": "Device inventory available",
                    "recommendation": "Proceed to Expert analysis",
                }
            
        except Exception as e:
            logger.warning(f"    ⚠ Schema validation failed: {e}")
            # Conservative: if we can't validate, allow Expert attempt
            return {
                "has_data": True,  # Let Expert try
                "available_tables": ["devices"],
                "missing_data": [],
                "reason": "Validation unavailable",
                "recommendation": "Proceeding with Expert Agent",
            }

