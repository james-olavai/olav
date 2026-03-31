import duckdb
from langchain_core.messages import HumanMessage, SystemMessage

import olav.agents.query_runner as query_runner_module
from olav.agents.query_runner import (
    _SCHEMA_REF,
    _build_messages,
    _contains_forbidden_sql_keyword,
    _execute_sql,
    _extract_sql,
    _format_result,
    _get_schema_context,
    _has_unquoted_internal_semicolon,
    _normalize_llm_content,
    run_nl_query,
)


def test_extract_sql_prefers_fenced_sql_block() -> None:
    text = "before```sql\nSELECT 1\n```after"
    assert _extract_sql(text) == "SELECT 1"


def test_extract_sql_falls_back_to_select_pattern() -> None:
    text = "SELECT * FROM v_interfaces; extra text"
    assert _extract_sql(text) == "SELECT * FROM v_interfaces"


def test_schema_reference_file_must_exist() -> None:
    assert _SCHEMA_REF.exists()


def test_get_schema_context_reads_reference_file() -> None:
    context = _get_schema_context()
    assert "v_interfaces" in context
    assert "v_bgp_neighbors" in context


def test_build_messages_prefers_summary_topology_views() -> None:
    system_msg, user_msg = _build_messages(
        "schema", "当前的 L2 拓扑是怎样的？哪些设备通过 LLDP 相连？"
    )
    assert "v_l2_topology_summary" in system_msg
    assert "v_device_neighbors_summary" in system_msg
    assert "v_l2_topology_summary" in user_msg
    assert "v_device_neighbors_summary" in user_msg


def test_build_messages_contains_primary_loopback_guidance() -> None:
    system_msg, user_msg = _build_messages("schema", "所有设备的 Loopback IP 是什么？")
    assert "primary loopback per device" in system_msg
    assert "primary loopback per device" in user_msg


def test_build_messages_enforce_semantic_view_priority() -> None:
    system_msg, user_msg = _build_messages("schema", "请给我当前网络拓扑摘要")
    assert "semantic views first" in system_msg
    assert "mapping_rules is a COMPAT TABLE" in user_msg


def test_extract_sql_supports_cte_pattern() -> None:
    text = "WITH ranked AS (SELECT 1 AS n) SELECT n FROM ranked; trailing text"
    assert _extract_sql(text) == "WITH ranked AS (SELECT 1 AS n) SELECT n FROM ranked"


def test_normalize_llm_content_keeps_string_content() -> None:
    content = "```sql\nSELECT 1\n```"
    assert _normalize_llm_content(content) == content


def test_normalize_llm_content_joins_text_blocks() -> None:
    content = [
        {"type": "text", "text": "```sql"},
        {"type": "text", "text": "SELECT 1"},
        {"type": "text", "text": "```"},
    ]
    assert _normalize_llm_content(content) == "```sql\nSELECT 1\n```"


def test_has_unquoted_internal_semicolon_detects_multi_statement() -> None:
    assert _has_unquoted_internal_semicolon("SELECT 1; SELECT 2") is True


def test_has_unquoted_internal_semicolon_allows_single_trailing_semicolon() -> None:
    assert _has_unquoted_internal_semicolon("SELECT 1;") is False


def test_has_unquoted_internal_semicolon_ignores_semicolon_in_string_literal() -> None:
    assert _has_unquoted_internal_semicolon("SELECT ';' AS marker") is False


def test_has_unquoted_internal_semicolon_ignores_semicolon_with_doubled_single_quotes() -> None:
    assert _has_unquoted_internal_semicolon("SELECT 'a'';''b' AS marker") is False


def test_has_unquoted_internal_semicolon_ignores_semicolon_in_line_comment() -> None:
    sql = "SELECT 1 -- this semicolon is comment;\n"
    assert _has_unquoted_internal_semicolon(sql) is False


def test_has_unquoted_internal_semicolon_ignores_semicolon_in_block_comment() -> None:
    sql = "SELECT /* comment ; inside */ 1"
    assert _has_unquoted_internal_semicolon(sql) is False


def test_contains_forbidden_sql_keyword_detects_delete_in_cte() -> None:
    sql = "WITH x AS (DELETE FROM t RETURNING id) SELECT id FROM x"
    assert _contains_forbidden_sql_keyword(sql) is True


def test_contains_forbidden_sql_keyword_ignores_keyword_in_string_and_comment() -> None:
    sql = "SELECT 'drop table x' AS text -- update noop\n"
    assert _contains_forbidden_sql_keyword(sql) is False


def test_format_result_renders_pipe_header_and_csv_like_rows() -> None:
    rows = [
        ("R1", "Loopback0", "1.1.1.1"),
        ("R2", "Loopback0", "2.2.2.2"),
    ]
    description = [
        ("device_name",),
        ("interface",),
        ("ip_address",),
    ]
    rendered = _format_result(rows, description)
    lines = rendered.splitlines()
    assert lines[0] == "device_name | interface | ip_address"
    assert lines[1] == "R1, Loopback0, 1.1.1.1"
    assert lines[2] == "R2, Loopback0, 2.2.2.2"


def test_format_result_handles_none_values_in_rows() -> None:
    rows = [("R2", "4.4.4.4", "65001", "Idle", None)]
    description = [
        ("device_name",),
        ("neighbor_ip",),
        ("neighbor_as",),
        ("state",),
        ("prefixes_received",),
    ]
    rendered = _format_result(rows, description)
    lines = rendered.splitlines()
    assert lines[0] == "device_name | neighbor_ip | neighbor_as | state | prefixes_received"
    assert lines[1] == "R2, 4.4.4.4, 65001, Idle, None"


def test_format_result_no_rows_returns_no_results_marker() -> None:
    rendered = _format_result([], [("col",)])
    assert rendered == "(no results)"


def test_format_result_preserves_description_column_order() -> None:
    rows = [("Idle", "R2", "4.4.4.4")]
    description = [
        ("state",),
        ("device_name",),
        ("neighbor_ip",),
    ]
    rendered = _format_result(rows, description)
    lines = rendered.splitlines()
    assert lines[0] == "state | device_name | neighbor_ip"
    assert lines[1] == "Idle, R2, 4.4.4.4"


def test_format_result_raises_on_row_column_length_mismatch() -> None:
    rows = [("R2", "4.4.4.4")]
    description = [
        ("device_name",),
        ("neighbor_ip",),
        ("state",),
    ]
    try:
        _format_result(rows, description)
    except ValueError as exc:
        assert "Row/column length mismatch" in str(exc)
    else:
        raise AssertionError("Expected ValueError for row/column length mismatch")


def test_format_result_raises_on_missing_description_for_non_empty_rows() -> None:
    rows = [("R1", "Loopback0", "1.1.1.1")]
    try:
        _format_result(rows, [])
    except ValueError as exc:
        assert "Missing column description" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing column description")


def test_execute_sql_formats_rows_from_temp_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "query_runner_execute_ok.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE demo (device_name VARCHAR, state VARCHAR)")
        conn.execute("INSERT INTO demo VALUES ('R2', 'Idle')")

    monkeypatch.setattr(query_runner_module, "MAIN_DB_PATH", db_path)

    rendered = _execute_sql("SELECT device_name, state FROM demo")
    lines = rendered.splitlines()
    assert lines[0] == "device_name | state"
    assert lines[1] == "R2, Idle"


def test_execute_sql_returns_error_payload_on_sql_failure(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "query_runner_execute_err.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE present_table (id INTEGER)")

    monkeypatch.setattr(query_runner_module, "MAIN_DB_PATH", db_path)

    sql = "SELECT * FROM missing_table"
    rendered = _execute_sql(sql)
    assert rendered.startswith("SQL error:"), rendered
    assert "missing_table" in rendered, rendered
    assert f"SQL: {sql}" in rendered, rendered


def test_execute_sql_returns_error_payload_on_render_failure(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "query_runner_execute_render_err.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE demo (device_name VARCHAR)")
        conn.execute("INSERT INTO demo VALUES ('R2')")

    monkeypatch.setattr(query_runner_module, "MAIN_DB_PATH", db_path)

    def _raise_render_error(rows, description):
        raise ValueError("render exploded")

    monkeypatch.setattr(query_runner_module, "_format_result", _raise_render_error)

    sql = "SELECT device_name FROM demo"
    rendered = _execute_sql(sql)
    assert rendered.startswith("SQL error:"), rendered
    assert "render exploded" in rendered, rendered
    assert f"SQL: {sql}" in rendered, rendered


def test_execute_sql_returns_no_results_marker_for_empty_result_set(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "query_runner_execute_empty.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE demo (device_name VARCHAR)")

    monkeypatch.setattr(query_runner_module, "MAIN_DB_PATH", db_path)

    rendered = _execute_sql("SELECT device_name FROM demo")
    assert rendered == "(no results)"


def test_run_nl_query_returns_schema_error_when_schema_missing(monkeypatch) -> None:
    def _raise_schema_error() -> str:
        raise FileNotFoundError("schema file missing")

    monkeypatch.setattr(query_runner_module, "_get_schema_context", _raise_schema_error)

    result = run_nl_query("所有设备的 Loopback IP 是什么？")
    assert result.startswith("Schema error:"), result
    assert "schema file missing" in result, result


def test_run_nl_query_returns_llm_error_when_llm_invoke_fails(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _FailingLLM:
        def invoke(self, _messages):
            raise RuntimeError("llm down")

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _FailingLLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)

    result = run_nl_query("BGP 邻居中 down 的有哪些？")
    assert result.startswith("LLM error:"), result
    assert "llm down" in result, result


def test_run_nl_query_happy_path_returns_execute_sql_output(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "```sql\nSELECT 1\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda sql: f"EXEC:{sql}")

    result = run_nl_query("当前的 L2 拓扑是怎样的？")
    assert result == "EXEC:SELECT 1"


def test_run_nl_query_calls_llm_factory_with_query_runner_agent_id(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    captured: dict[str, object] = {}

    class _Resp:
        content = "```sql\nSELECT 1\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            captured.update(kwargs)
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda _sql: "ok")

    result = run_nl_query("测试 query runner agent_id")
    assert result == "ok"
    assert captured.get("agent_id") == "query_runner"
    assert captured.get("temperature") == 0


def test_run_nl_query_accepts_non_fenced_sql_response(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "SELECT device_name FROM v_interfaces; trailing explanation"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda sql: f"EXEC:{sql}")

    result = run_nl_query("给我接口列表")
    assert result == "EXEC:SELECT device_name FROM v_interfaces"


def test_run_nl_query_sends_system_and_human_messages(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    captured: dict[str, object] = {}

    class _Resp:
        content = "```sql\nSELECT 1\n```"

    class _LLM:
        def invoke(self, messages):
            captured["messages"] = messages
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda _sql: "ok")

    question = "当前的 L2 拓扑是怎样的？"
    result = run_nl_query(question)
    assert result == "ok"

    messages = captured.get("messages")
    assert isinstance(messages, list)
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert question in str(messages[1].content)


def test_run_nl_query_handles_block_content_response(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = [{"type": "text", "text": "```sql\nSELECT 1\n```"}]

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda sql: f"EXEC:{sql}")

    result = run_nl_query("当前的 L2 拓扑是怎样的？")
    assert result == "EXEC:SELECT 1"


def test_run_nl_query_returns_explicit_error_on_empty_sql_content(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = ""

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)

    result = run_nl_query("空 SQL 响应测试")
    assert result == "LLM error: empty SQL response"


def test_run_nl_query_returns_explicit_error_when_content_missing(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        pass

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)

    result = run_nl_query("缺失 content 响应测试")
    assert result == "LLM error: empty SQL response"


def test_run_nl_query_returns_invalid_sql_error_for_plain_text_response(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "Here is your answer without SQL"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)

    result = run_nl_query("无 SQL 内容测试")
    assert result == "LLM error: invalid SQL response"


def test_run_nl_query_returns_invalid_sql_error_for_fenced_non_sql(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "```sql\nDROP TABLE x\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)

    result = run_nl_query("非查询 SQL 测试")
    assert result == "LLM error: invalid SQL response"


def test_run_nl_query_rejects_multi_statement_sql_response(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "```sql\nSELECT 1; DROP TABLE x\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)

    result = run_nl_query("多语句 SQL 测试")
    assert result == "LLM error: multiple SQL statements not allowed"


def test_run_nl_query_allows_single_statement_with_trailing_semicolon(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "```sql\nSELECT 1;\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda sql: f"EXEC:{sql}")

    result = run_nl_query("尾分号 SQL 测试")
    assert result == "EXEC:SELECT 1;"


def test_run_nl_query_allows_semicolon_inside_string_literal(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "```sql\nSELECT ';' AS marker\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda sql: f"EXEC:{sql}")

    result = run_nl_query("字符串分号测试")
    assert result == "EXEC:SELECT ';' AS marker"


def test_run_nl_query_allows_semicolon_with_doubled_single_quotes(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "```sql\nSELECT 'a'';''b' AS marker\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda sql: f"EXEC:{sql}")

    result = run_nl_query("转义引号分号测试")
    assert result == "EXEC:SELECT 'a'';''b' AS marker"


def test_run_nl_query_allows_semicolon_in_sql_comment(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "```sql\nSELECT 1 -- comment ; stays in comment\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)
    monkeypatch.setattr(query_runner_module, "_execute_sql", lambda sql: f"EXEC:{sql}")

    result = run_nl_query("注释分号测试")
    assert result == "EXEC:SELECT 1 -- comment ; stays in comment"


def test_run_nl_query_rejects_non_read_only_sql_even_with_with_clause(monkeypatch) -> None:
    monkeypatch.setattr(query_runner_module, "_get_schema_context", lambda: "schema")

    class _Resp:
        content = "```sql\nWITH x AS (DELETE FROM t RETURNING id) SELECT id FROM x\n```"

    class _LLM:
        def invoke(self, _messages):
            return _Resp()

    class _FakeFactory:
        @staticmethod
        def get_chat_model(*args, **kwargs):
            return _LLM()

    monkeypatch.setattr(query_runner_module, "LLMFactory", _FakeFactory)

    result = run_nl_query("只读 SQL 防护测试")
    assert result == "LLM error: non-read-only SQL response"
