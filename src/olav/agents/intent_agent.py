"""
IntentAgent - Fast Path Execution Orchestrator

Implements the Fast Path architecture described in docs/00_roadmap.md:
- Intent recognition and execution plan caching
- Direct execution for high-confidence cached plans (Tier 0 optimization)
- Result validation and automatic supplemental queries
- Target: 3-5s for cached queries (vs 10-14s current)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from olav.cache import cache as olav_cache  # 新的统一缓存
from olav.core.llm import LLMFactory
from olav.core.skill_config import SkillConfig  # P1: Load cache config from SKILL
from olav.core.unified_database import UnifiedDatabase
from olav.lib.data_gateway import get_gateway

logger = logging.getLogger(__name__)


class IntentAgent:
    """
    Intent Agent - Fast Path Execution Orchestrator

    The Intent Agent is the central coordinator for the fast path architecture:
    1. Check intent cache for pre-computed execution plans
    2. For exact match hits, execute directly (Fast Path)
    3. Validate results and supplement with additional queries if needed
    4. Render final Markdown output
    """

    def __init__(self) -> None:
        """Initialize Intent Agent with necessary components."""
        self.llm = LLMFactory.get_chat_model()
        self.gw = get_gateway()

    async def process_query(self, query: str) -> str:
        """
        Process a user query with Fast Path optimization.

        Args:
            query: User's natural language query

        Returns:
            Markdown formatted response
        """
        # Phase 1: Check intent cache for exact match
        cached_plan = await self._check_intent_cache(query)

        if cached_plan:
            # Fast Path: Exact match, execute directly
            logger.info("Fast Path: Using cached plan (exact match)")
            # Execute the cached plan directly（no wrapper dict）
            return await self._execute_plan(cached_plan)

        # Phase 2: No cached plan, fall back to Orchestrator
        logger.info("No cached plan found, delegating to Orchestrator")
        return await self._orchestrate_query(query)

    async def _check_intent_cache(
        self, query: str, skill_id: str = "network-query"
    ) -> dict[str, Any] | None:
        """
        Check intent cache for an exact match execution plan.
        P1: Load cache strategy from SKILL.md configuration

        Args:
            query: User's query
            skill_id: Skill identifier (default: network-query)

        Returns:
            Cached execution_plan, or None
        """
        # P1: Load cache config from SKILL.md
        cache_cfg = SkillConfig.get_cache_config(skill_id)

        if not cache_cfg.get("enabled", True):
            logger.debug(f"Cache disabled for skill {skill_id}")
            return None

        # Execute cache lookup with SKILL-configured strategy
        cached_result = olav_cache.get_intent(
            query,
            match_mode=cache_cfg.get("match_mode", "exact"),
            confidence_threshold=cache_cfg.get("confidence_threshold", 1.0),
        )

        if not cached_result:
            return None

        logger.info(
            f"✅ Intent cache HIT ({skill_id}, {cache_cfg.get('match_mode')}): {query[:50]}"
        )

        # Return execution_plan directly
        return cached_result

    async def _execute_plan(self, plan: dict[str, Any]) -> str:
        """
        Execute a pre-computed execution plan.

        Args:
            plan: Execution plan with steps (SQL/CLI queries)

        Returns:
            Markdown formatted response
        """
        results = []

        for step in plan.get("steps", []):
            step_type = step.get("type", "sql")

            if step_type == "sql":
                # SQL SubAgent execution
                data = await self._execute_sql_step(step)
                results.append({"type": "sql", "data": data})

            elif step_type == "cli":
                # CLI Specialist execution
                data = await self._execute_cli_step(step)
                results.append({"type": "cli", "data": data})

        # Phase 3: Result validation and supplementation
        return await self._validate_and_render(results, plan)

    async def _execute_sql_step(self, step: dict[str, Any]) -> Any:
        """
        Execute a single SQL step from the execution plan.

        Args:
            step: SQL step with query

        Returns:
            Query results (list of dicts)
        """
        query = step.get("query")

        if not query:
            raise ValueError("SQL query is required but not provided")

        try:
            results = self.gw.query_snapshots(query)
            logger.info(f"SQL executed successfully: {query[:50]}...")
            return results
        except Exception as e:
            logger.error(f"SQL execution failed: {e}")
            raise RuntimeError(f"SQL execution failed: {e}") from e

    async def _execute_cli_step(self, step: dict[str, Any]) -> str:
        """
        Execute a single CLI step from the execution plan.

        Args:
            step: CLI step with command

        Returns:
            CLI output string
        """
        from olav.shared.tools.network_executor import get_executor

        device = step.get("device") or ""
        command = step.get("command") or ""

        executor = get_executor()
        result = executor.execute_with_parsing(device, command)

        if result.success:
            logger.info(f"CLI executed successfully: {device} - {command[:30]}...")
            return result.output or result.data
        else:
            logger.error(f"CLI execution failed: {result.error}")
            raise RuntimeError(f"CLI execution failed: {result.error}")

    async def _validate_and_render(
        self, results: list[dict[str, Any]], plan: dict[str, Any]
    ) -> str:
        """
        Validate result completeness and render Markdown.

        Args:
            results: List of execution results (SQL/CLI)
            plan: Original execution plan

        Returns:
            Markdown formatted response
        """
        validation = await self._validate_results(results, plan)

        if validation.get("is_complete"):
            # Data is complete: directly render Markdown
            return self._render_markdown(results, plan)
        else:
            # Data is insufficient: supplement with additional queries
            if validation.get("missing_fields"):
                # Need additional SQL queries
                additional_data = await self._generate_additional_queries(
                    validation["missing_fields"], results
                )
                results.extend(additional_data)

            if validation.get("needs_realtime"):
                # Need real-time CLI data
                additional_data = await self._execute_cli_commands(
                    validation.get("required_commands", [])
                )
                results.extend(additional_data)

            # Re-validate after supplementation
            validation = await self._validate_results(results, plan)

        # Final rendering
        return self._render_markdown(results, plan)

    async def _validate_results(
        self, results: list[dict[str, Any]], plan: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Validate result completeness.

        Args:
            results: Execution results
            plan: Original execution plan

        Returns:
            Validation dict with is_complete, missing_fields, needs_realtime, required_commands
        """
        validation = {
            "is_complete": True,
            "missing_fields": [],
            "needs_realtime": False,
            "required_commands": [],
        }

        # Check each result
        for result in results:
            result_type = result.get("type")
            data = result.get("data")

            if not data:
                # Empty result - missing data
                validation["is_complete"] = False

                if result_type == "sql":
                    validation["needs_realtime"] = True
                else:
                    validation["missing_fields"].append(f"{result_type}_result")

        # Check if plan requires fields that are not in results
        plan_requirements = plan.get("required_fields", [])
        result_fields = []

        for result in results:
            if isinstance(result.get("data"), list) and result["data"]:
                first_item = result["data"][0] if result["data"] else {}
                result_fields.extend(first_item.keys())

        missing = [f for f in plan_requirements if f not in result_fields]

        if missing:
            validation["is_complete"] = False
            validation["missing_fields"].extend(missing)

        return validation

    async def _generate_additional_queries(
        self, missing_fields: list[str], results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Generate and execute additional SQL queries for missing fields.

        Args:
            missing_fields: List of missing field names
            results: Existing results

        Returns:
            List of additional query results
        """
        additional_results = []

        for field in missing_fields:
            # Generate SQL to fetch the missing field
            # Use fixed column name in SQL but parameterize where possible
            # Note: Field names cannot be parameterized in SQL, but we validate it's alphanumeric
            if not field.isalnum():
                continue
            sql = f"SELECT {field} FROM v_interfaces WHERE device != 'NULL' LIMIT 10"  # noqa: S608

            with UnifiedDatabase() as db:
                try:
                    data = db.query(sql)
                    additional_results.append(
                        {
                            "type": "sql",
                            "data": data,
                        }
                    )
                    logger.info(f"Additional query executed for field: {field}")
                except Exception as e:
                    logger.error(f"Additional query failed for field {field}: {e}")
                    logger.error(f"Additional query failed for field {field}: {e}")

        return additional_results

    async def _execute_cli_commands(self, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Execute CLI commands for real-time data.

        Args:
            commands: List of CLI command dicts

        Returns:
            List of CLI results
        """
        results = []

        for cmd in commands:
            try:
                data = await self._execute_cli_step(cmd)
                results.append(
                    {
                        "type": "cli",
                        "data": data,
                    }
                )
            except Exception as e:
                logger.error(f"CLI command execution failed: {e}")
                results.append(
                    {
                        "type": "cli",
                        "data": f"Error: {str(e)}",
                    }
                )

        return results

    def _render_markdown(self, results: list[dict[str, Any]], plan: dict[str, Any]) -> str:
        """
        Render results as Markdown.

        Args:
            results: Execution results
            plan: Original execution plan

        Returns:
            Markdown formatted string
        """
        output = []

        for result in results:
            result_type = result.get("type")
            data = result.get("data")

            if result_type == "sql":
                # Format SQL results as Markdown table
                if isinstance(data, list) and data:
                    output.append(self._format_sql_table(data))
                elif data:
                    output.append(f"```json\n{json.dumps(data, indent=2, default=str)}\n```")
                else:
                    output.append("*No data returned*\n")

            elif result_type == "cli":
                # Format CLI output as Markdown code block
                if data:
                    output.append(f"```\n{data}\n```\n")
                else:
                    output.append("*Command failed*\n")

        # Add summary if plan requires it
        if plan.get("requires_insights"):
            insights = self._generate_insights(results)
            output.append(f"\n## 分析\n{insights}")

        return "\n\n".join(output)

    def _format_sql_table(self, data: list[dict[str, Any]]) -> str:
        """
        Format SQL results as Markdown table.

        Args:
            data: List of row dicts

        Returns:
            Markdown table string
        """
        if not data:
            return "*No results*\n"

        # Get column names from first row
        columns = list(data[0].keys())
        headers = " | ".join(f"**{col}**" for col in columns)
        separator = "|".join(["---"] * (len(columns) + 1))

        rows = []
        for row in data:
            row_values = " | ".join(str(row.get(col, "")) for col in columns)
            rows.append(f"| {row_values} |")

        table = f"| {headers} |\n{separator}\n" + "\n".join(rows)
        return table

    def _generate_insights(self, results: list[dict[str, Any]]) -> str:
        """
        Generate insights from results.

        Args:
            results: Execution results

        Returns:
            Insights text
        """
        insights = []

        # Count SQL vs CLI queries
        sql_count = sum(1 for r in results if r.get("type") == "sql")
        cli_count = sum(1 for r in results if r.get("type") == "cli")

        insights.append(f"- SQL 查询: {sql_count} 次")
        insights.append(f"- CLI 命令: {cli_count} 次")

        return "\n".join(insights)

    async def _orchestrate_query(self, query: str) -> str:
        """
        Fallback to Orchestrator for complex queries without cached plans.

        Args:
            query: User's query

        Returns:
            Markdown formatted response from Orchestrator
        """
        from olav.agents.orchestrator import orchestrate_query

        # Call the real orchestrator with full ReAct loop
        logger.info(f"Delegating to Orchestrator: {query}")
        result = await orchestrate_query(query)
        return result

    async def save_to_intent_cache(self, query: str, plan: dict[str, Any]) -> None:
        """
        Save a successful execution plan to intent cache.

        Args:
            query: Original query
            plan: Execution plan
        """
        # 使用新的统一缓存系统
        olav_cache.set_intent(query, plan)
