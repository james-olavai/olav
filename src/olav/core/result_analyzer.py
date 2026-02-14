"""Result Analyzer - Generate markdown summaries from query results using LLM.

Purpose:
  Converts raw SQL results into human-readable markdown analysis.
  ✅ Is Configuration-Driven: Loads prompt from SKILL.md
  ❌ No Hardcoding: All analysis instructions in SKILL.md
  
Architecture:
  User Query
    ↓
  SQL Generated
    ↓
  Results Return
    ↓
  Load analyzer prompt from SKILL.md
    ↓
  Send results + prompt to LLM
    ↓
  Get markdown analysis
"""

import json
import logging
from typing import Any

from olav.core.skill_loader import get_skill_loader
from olav.core.llm import LLMFactory
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


def analyze_results(
    results: list[dict[str, Any]],
    user_query: str,
    sql_query: str,
) -> str:
    """Generate markdown summary from query results using LLM.
    
    ✅ SKILL-Driven: Loads prompt from SKILL.md
    ✅ No Hardcoding: All instructions from configuration
    
    Args:
        results: List of result dictionaries
        user_query: Original user query
        sql_query: Generated SQL query
    
    Returns:
        Markdown-formatted summary
    """
    logger.debug(f"[ResultAnalyzer] Starting analysis for {len(results)} results")
    
    if not results:
        logger.debug("[ResultAnalyzer] No results to analyze")
        return "## Query Results\n\n⚠️ No data found matching the query."
    
    try:
        # Load analyzer prompt from SKILL (Configuration-Driven!)
        logger.debug("[ResultAnalyzer] Loading analyzer prompt from SKILL...")
        skill_loader = get_skill_loader()
        skill_loader.load_all()
        
        analyzer_prompt = skill_loader.load_system_prompt(
            "network-query",
            prompt_key="result_analyzer",
            template_vars={}
        )
        
        if not analyzer_prompt:
            logger.warning("[ResultAnalyzer] Failed to load analyzer prompt from SKILL, using fallback")
            return _fallback_analysis(results, user_query, sql_query)
        
        logger.debug(f"[ResultAnalyzer] Loaded prompt ({len(analyzer_prompt)} chars)")
        
        # Prepare data for LLM analysis
        data_summary = {
            "result_count": len(results),
            "columns": list(results[0].keys()) if results else [],
            "sample_rows": results[:5],  # Send first 5 rows as samples
            "user_query": user_query,
            "sql_query": sql_query,
        }
        
        # Build prompt for LLM
        logger.debug("[ResultAnalyzer] Initializing LLM...")
        llm = LLMFactory.get_chat_model()
        
        human_message = f"""Please analyze these query results and generate a Markdown summary:

**User Query:** {user_query}

**SQL Query:**
```sql
{sql_query}
```

**Results:** {len(results)} row(s) found

**Data Structure:**
- Columns: {', '.join(data_summary['columns'])}
- Sample data (first few rows):
```json
{json.dumps(data_summary['sample_rows'], indent=2, default=str)}
```

Generate a clear Markdown analysis following the format and rules in the system prompt."""
        
        messages = [
            SystemMessage(content=analyzer_prompt),
            HumanMessage(content=human_message),
        ]
        
        logger.debug("[ResultAnalyzer] Sending results to LLM for analysis...")
        response = llm.invoke(messages)
        
        markdown = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        logger.debug(f"[ResultAnalyzer] ✅ Analysis complete ({len(markdown)} chars)")
        
        return markdown
        
    except Exception as e:
        logger.error(f"[ResultAnalyzer] ❌ Failed to generate analysis: {e}", exc_info=True)
        return _fallback_analysis(results, user_query, sql_query)


def _fallback_analysis(
    results: list[dict[str, Any]],
    user_query: str,
    sql_query: str,
) -> str:
    """Fallback analysis when LLM fails (simple hardcoded format).
    
    This is only used as fallback when SKILL loading or LLM fails.
    """
    markdown = "## Query Results\n\n"
    markdown += f"📊 **Found {len(results)} record(s)**\n\n"
    
    # Simple table format
    if results:
        columns = list(results[0].keys())
        markdown += "### Data\n\n"
        markdown += "| " + " | ".join(columns[:5]) + " |\n"
        markdown += "| " + " | ".join(["---"] * min(5, len(columns))) + " |\n"
        
        for row in results[:3]:
            values = []
            for col in columns[:5]:
                val = str(row.get(col, ""))[:30]
                values.append(val if len(str(row.get(col, ""))) <= 30 else val + "...")
            markdown += "| " + " | ".join(values) + " |\n"
        
        if len(results) > 3:
            markdown += f"\n*... and {len(results)-3} more rows*\n"
    
    # SQL reference
    markdown += "\n---\n\n### SQL Query\n\n"
    markdown += f"```sql\n{sql_query}\n```\n"
    
    return markdown

