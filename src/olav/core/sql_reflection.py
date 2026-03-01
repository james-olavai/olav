import logging
from typing import Any

from olav.core.config import get_config
from olav.core.defaults import SQL_REFLECTION_MAX_RETRIES
from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = SQL_REFLECTION_MAX_RETRIES


class SQLReflectionError(Exception):
    def __init__(self, original_error: str, sql_attempts: list[str]):
        self.original_error = original_error
        self.sql_attempts = sql_attempts
        super().__init__(
            f"SQL reflection failed after {len(sql_attempts)} attempts: {original_error}"
        )


class SQLReflector:
    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        db_path: str | None = None,
    ):
        self.max_retries = max_retries

        if db_path is None:
            config = get_config()
            db_path = config.paths.main_db

        self.db_path = db_path
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            config = get_config()
            self._llm = LLMFactory.get_chat_model(
                model_name=config.llm.model,
                temperature=0.0,
                agent_id="sql-reflector",
            )
        return self._llm

    def execute(self, sql: str, schema_context: str = "") -> dict[str, Any]:
        attempts = []
        current_sql = sql
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            logger.info(f"SQL Reflection attempt {attempt}/{self.max_retries}")
            attempts.append(
                {
                    "attempt": attempt,
                    "sql": current_sql,
                    "error": None,
                }
            )

            try:
                import duckdb

                conn = duckdb.connect(str(self.db_path), read_only=True)
                result = conn.execute(current_sql)

                columns = [desc[0] for desc in result.description] if result.description else []
                rows = result.fetchall()

                results = []
                for row in rows:
                    results.append(dict(zip(columns, row, strict=False)))

                conn.close()

                logger.info(f"SQL execution succeeded on attempt {attempt}")

                return {
                    "success": True,
                    "results": results,
                    "columns": columns,
                    "row_count": len(results),
                    "error": None,
                    "attempts": attempts,
                    "final_sql": current_sql,
                }

            except Exception as e:
                last_error = str(e)
                attempts[-1]["error"] = last_error

                logger.warning(f"SQL execution failed on attempt {attempt}: {last_error}")

                if attempt < self.max_retries:
                    current_sql = self._correct_sql(
                        original_sql=sql,
                        failed_sql=current_sql,
                        error=last_error,
                        schema_context=schema_context,
                    )

                    if len(attempts) > 1 and current_sql == attempts[-2]["sql"]:
                        logger.warning("SQL correction produced same SQL, stopping retries")
                        break
                        logger.warning("SQL correction produced same SQL, stopping retries")
                        break

        return {
            "success": False,
            "results": [],
            "columns": [],
            "row_count": 0,
            "error": last_error,
            "attempts": attempts,
            "final_sql": current_sql,
        }

    def _correct_sql(
        self,
        original_sql: str,
        failed_sql: str,
        error: str,
        schema_context: str,
    ) -> str:
        llm = self._get_llm()

        prompt = f"""You are a SQL expert. The following SQL query failed to execute.

## Database Schema
{schema_context or "No schema information provided."}

## Original Query
{original_sql}

## Failed SQL
{failed_sql}

## Error Message
{error}

## Task
Analyze the error and fix the SQL query. Return ONLY the corrected SQL query, nothing else.

The corrected SQL:"""

        try:
            response = llm.invoke(prompt)
            corrected = response.content.strip()

            if corrected.startswith("```sql"):
                corrected = corrected[7:]
            if corrected.startswith("```"):
                corrected = corrected[3:]
            if corrected.endswith("```"):
                corrected = corrected[:-3]

            corrected = corrected.strip()

            logger.info(f"LLM corrected SQL: {corrected[:100]}...")
            return corrected

        except Exception as e:
            logger.error(f"LLM correction failed: {e}")
            return failed_sql

    def execute_with_schema(self, sql: str) -> dict[str, Any]:
        schema_context = self._get_schema_context()
        return self.execute(sql, schema_context)

    def _get_schema_context(self) -> str:
        import duckdb

        schema_parts = []

        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)

            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()

            for (table_name,) in tables:
                columns = conn.execute(f"""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = '{table_name}'
                    ORDER BY ordinal_position
                """).fetchall()

                col_strs = [f"  - {col} ({dtype})" for col, dtype in columns]
                schema_parts.append(f"### {table_name}\n" + "\n".join(col_strs))

            conn.close()

        except Exception as e:
            logger.warning(f"Failed to get schema context: {e}")
            return f"Error retrieving schema: {e}"

        return "\n\n".join(schema_parts) if schema_parts else "No schema available"


def execute_sql_with_reflection(sql: str, max_retries: int = 3) -> dict[str, Any]:
    reflector = SQLReflector(max_retries=max_retries)
    return reflector.execute_with_schema(sql)
