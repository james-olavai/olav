"""Smart SQL Query Tool - Skill-specific wrapper with LangChain Tool interface.

This is a lightweight implementation inspired by LangChain SQL Agent but:
- No heavy SQLDatabase dependency
- Direct integration with DeepAgents ReAct loop
- Auto schema discovery without manual inspect_schema calls
- SQL error self-correction via agent retry
"""

from langchain_core.tools import tool


@tool
def smart_sql_query(query: str | None = None, sql: str | None = None) -> str:
    """Execute intelligent SQL query with automatic schema discovery.

    This tool replaces query_database + inspect_schema workflow with:
    1. Auto schema context (no manual calls needed)
    2. SQL generation guidance
    3. Error self-correction (via agent ReAct loop)

    Inspired by LangChain SQL Agent but optimized for OLAV's needs.

    Args:
        query: Natural language query (e.g., "有多少个设备?")
        sql: Direct SQL to execute (for agent-generated queries)

    Returns:
        Query results or schema context for SQL generation

    Example Usage by Agent:
        # Step 1: Agent calls with natural language
        result = smart_sql_query(query="有多少个设备?")
        # Returns: Schema context + guidance

        # Step 2: Agent generates SQL based on context
        result = smart_sql_query(sql="SELECT COUNT(*) FROM devices")
        # Returns: Query results

        # Step 3: If error, agent retries with corrected SQL
        result = smart_sql_query(sql="SELECT COUNT(*) as count FROM devices")
        # Returns: Success

    Benefits over old workflow:
    - No need to manually call inspect_schema() first
    - Schema context always fresh
    - Error messages include schema hints
    - Single tool instead of 2 (query_database + inspect_schema)
    """
    import json
    import subprocess
    from pathlib import Path

    # Find tool script
    tool_script = Path(__file__).parent.parent.parent.parent / "shared" / "tools" / "smart_sql_query.py"

    if not tool_script.exists():
        return f"❌ Tool script not found: {tool_script}"

    # Prepare input
    input_data = {}
    if query:
        input_data["query"] = query
    if sql:
        input_data["sql"] = sql

    try:
        result = subprocess.run(
            ["python3", str(tool_script)],
            input=json.dumps(input_data, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=True,
        )

        output = json.loads(result.stdout)

        # Format output based on status
        if output["status"] == "success":
            if "data" in output:
                return json.dumps(
                    {
                        "data": output["data"],
                        "count": output.get("count", len(output["data"])),
                        "sql": output.get("sql", ""),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                # Schema context only
                return output["schema_context"]

        elif output["status"] == "needs_sql_generation":
            # Guide agent to generate SQL
            return f"""Schema context for SQL generation:

{output['schema_context']}

Your task: Generate SQL for: "{output['user_query']}"

Use smart_sql_query(sql="YOUR_GENERATED_SQL") to execute."""

        elif output["status"] == "error":
            # Return error with schema hints
            error_msg = f"❌ SQL Error: {output['error']}\n\n"
            if "schema_context" in output:
                error_msg += f"Schema context:\n{output['schema_context']}\n\n"
            error_msg += f"Attempted SQL: {output.get('attempted_sql', 'N/A')}\n"
            error_msg += "Please retry with corrected SQL."
            return error_msg

        return json.dumps(output, ensure_ascii=False, indent=2)

    except subprocess.CalledProcessError as e:
        return f"❌ Execution error: {e.stderr}"
    except json.JSONDecodeError as e:
        return f"❌ JSON error: {e}"
    except Exception as e:
        return f"❌ Unexpected error: {e}"
