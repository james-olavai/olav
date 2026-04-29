"""Data Export Tool - 极简文件导出工具

统一数据导出功能，支持多种格式自动检测。
只有Orchestrator可以调用此工具，SubAgent不应直接写文件。

核心特性：
- 零硬编码：无关键词映射，无格式判断
- 自动检测：从数据内容自动推断格式
- 统一输出：所有文件到 exports/ 目录
- 简单接口：3个参数，智能默认值
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


@tool
def format_and_export(
    data: str,
    filename: str | None = None,
    format: str | None = None,
    subdir: str | None = None,
) -> dict[str, Any]:
    """Save STRING content to a file under exports/.

    The `data` parameter is the literal file content as a STRING.
    It is NOT a configuration dict, NOT the return of a previous tool,
    NOT a wrapper. The string you pass is what gets written byte-for-byte
    (after format-specific encoding for CSV/JSON/YAML).

    ANTI-PATTERNS (these will FAIL with a Pydantic validation error):

        format_and_export(data={"format":"md", "filename":"x"})   # ❌ dict
        format_and_export(data={"path":"...", "size":1234})       # ❌ dict
        format_and_export(data='"my content"')                    # ❌ JSON-quoted

    CORRECT calls — `data` is the actual string content:

        format_and_export(
            data="# Devices\\n\\n| Name | IP |\\n|------|-----|\\n| R1 | 1.2.3.4 |",
            format="md",
            filename="devices_summary",
        )
        # → exports/reports/devices_summary.md

        format_and_export(
            data='[{"hostname":"R1","ip":"10.0.0.1"},{"hostname":"R2","ip":"10.0.0.2"}]',
            format="csv",
            filename="devices",
        )
        # → exports/devices.csv

        format_and_export(
            data="#!/usr/bin/env bash\\nfor h in R1 R2; do ssh $h ...; done",
            format="sh",
            filename="backup",
        )
        # → exports/scripts/backup.sh

    Args:
        data:     File content as a STRING. For CSV/JSON output, pass the
                  JSON-serialised string of an array/object — the tool
                  will parse it. For markdown/sh/text, pass the literal
                  text. NEVER pass a dict, a previous tool result, or
                  a configuration object.
        filename: Basename WITHOUT extension. Auto-generated if omitted.
        format:   md / json / txt / csv / yaml / mmd / sh — auto-detected
                  from `data` content if omitted.
        subdir:   Subdir under exports/. Auto-routed by format if omitted:
                  md/mmd/txt → exports/reports/, csv/json/yaml → exports/,
                  sh/py → exports/scripts/.

    Returns:
        {"path": "exports/.../file.ext", "absolute_path": "...", "size": 1234, "format": "md"}
    """
    # 1. Determine output directory based on format.
    # WRITER-WRONG-PATH (R82): the previous import was
    # ``from olav.core.config import EXPORTS_DIR as REPORTS_DIR`` and the
    # csv/json branches used ``REPORTS_DIR.parent`` — that's the project
    # root, not exports/.  Fresh-demo verification ended up writing
    # ``devices.csv`` straight to ``~/olav-demo/``.  Fixed: data files
    # land under ``exports/`` directly; narrative reports under
    # ``exports/reports/``.
    from olav.core.config import EXPORTS_DIR

    # R100/S2: strip leading/trailing literal quotes that small models
    # (qwen3.6-27b-dense empirically observed 2026-04-29 demo7 Ch8 v5)
    # bake into short string-typed args via their JSON-construction
    # heuristic.  Behaviour: long fields like ``data`` come through clean
    # as plain strings, but short identifier-like fields (filename,
    # format, subdir) sometimes arrive as ``'"reports"'`` — literal
    # quote characters are part of the value, not the JSON wire format.
    # The ``json.loads`` round-trip in the OpenAI compat path doesn't
    # detect this because ``'"reports"'`` is technically valid JSON for
    # a string with content ``"reports"`` if the outer quotes are
    # interpreted as JSON delimiters; in practice the doubled quoting
    # ends up in the Python string.  Defensive strip protects against
    # both single- and double-quoted leakage.
    def _strip_quote_leak(s: str | None) -> str | None:
        if not isinstance(s, str):
            return s
        s = s.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            s = s[1:-1].strip()
        return s

    filename = _strip_quote_leak(filename)
    format = _strip_quote_leak(format)
    subdir = _strip_quote_leak(subdir)

    # Coerce LLM-serialised "null" / "None" / "" subdir back to Python None
    # — small models often pass these as literal strings via JSON tool args.
    if isinstance(subdir, str) and subdir.strip().lower() in ("", "null", "none"):
        subdir = None

    # Drop a redundant "exports" / "exports/" prefix the agent may have
    # added — ``subdir`` is already relative to EXPORTS_DIR so passing
    # ``subdir="exports"`` produces ``exports/exports/...``.  Strip
    # leading slashes too so ``subdir="/scripts"`` doesn't escape.
    if isinstance(subdir, str):
        cleaned = subdir.strip().lstrip("/")
        # Handle "exports", "exports/", "exports/foo" — collapse leading
        # ``exports/`` and use the remainder; bare "exports" → None.
        if cleaned == EXPORTS_DIR.name:
            subdir = None
        elif cleaned.startswith(EXPORTS_DIR.name + "/"):
            subdir = cleaned[len(EXPORTS_DIR.name) + 1:] or None
        else:
            subdir = cleaned or None

    if subdir is not None:
        # Explicit subdir overrides all automatic routing.
        # subdir is relative to EXPORTS_DIR (e.g. "scripts" → exports/scripts/)
        output_dir = EXPORTS_DIR / subdir
    elif format and format.lower() in ("csv", "json", "yaml", "yml"):
        output_dir = EXPORTS_DIR  # exports/<file>.csv
    elif format and format.lower() in ("md", "txt", "mmd"):
        output_dir = EXPORTS_DIR / "reports"  # exports/reports/<file>.md
    else:
        output_dir = None  # resolved after format detection

    # 2. Parse JSON strings into native Python objects.
    #    LLM tool calls often pass query_database results as JSON-encoded
    #    strings (the only legit way to pass list[dict] through OpenAI's
    #    string-typed `arguments` field).  Converting early ensures
    #    _detect_format and _write_csv see list[dict].
    #
    #    R100/S2 (2026-04-29): the legacy dict-extraction block (which
    #    handled {"content": "..."} and {"# title": "md"}) was removed
    #    because the strict ``data: str`` Pydantic schema now rejects
    #    dicts before this function runs.  If the LLM passes a dict
    #    arg, it gets a Pydantic ValidationError with the schema spec
    #    in the error message — that is the desired feedback signal.
    if isinstance(data, str):
        stripped = data.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, (list, dict)):
                    data = parsed
            except (json.JSONDecodeError, ValueError):
                pass

    # 4. Auto-detect format (if not specified)
    if not format:
        format = _detect_format(data)

    # 4. Resolve output_dir if not yet determined (only when subdir=None and format was auto-detected)
    if output_dir is None:
        if format in ("csv", "json", "yaml", "yml", "sh"):
            output_dir = EXPORTS_DIR  # exports/<file>.csv
        else:
            output_dir = EXPORTS_DIR / "reports"  # exports/reports/<file>.md

    output_dir.mkdir(parents=True, exist_ok=True)

    # Coerce LLM-serialised "null" / "None" filename to Python None too.
    if isinstance(filename, str) and filename.strip().lower() in ("", "null", "none"):
        filename = None

    # 5. Auto-generate filename (if not specified)
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{timestamp}"

    # 6. Sanitize filename and handle existing extension
    #    If filename has extension, we use it as the format if format was auto-detected
    from pathlib import PurePath
    p = PurePath(filename)
    if p.suffix and p.suffix[1:].lower() in ("md", "json", "txt", "csv", "yaml", "yml", "mmd", "sh"):
        # If user provided extension, and it's a known one, split it
        actual_format = p.suffix[1:].lower()
        filename = p.stem
        # If format was auto-detected, override with filename's extension
        # If format was explicitly passed, verify they match or override?
        # Here we let explicit 'format' arg win if provided, otherwise filename's ext wins.
        if not format or format == "md": # md is a common fallback
             format = actual_format
    else:
        filename = p.name

    if ".." in filename or filename.startswith("/"):
        raise ValueError(f"Invalid filename: {filename}. Cannot contain '..' or start with '/'")

    # 7. Build full path
    filepath = output_dir / f"{filename}.{format}"

    # 7. Write file based on format
    _write_file(filepath, data, format)

    # 8. Return result with relative path for display
    return {
        "path": str(filepath.relative_to(Path.cwd())),  # 相对路径：exports/reports/xxx.csv
        "absolute_path": str(filepath.absolute()),
        "size": filepath.stat().st_size,
        "format": format,
    }


def _detect_format(data: Any) -> str:  # noqa: ANN401
    """
    从数据内容自动检测格式

    检测规则：
    - 以 # 开头或包含 ## → Markdown
    - 以 { 或 [ 开头 → JSON
    - dict/list 类型 → JSON
    - 其他字符串 → Text

    Args:
        data: 要检测的数据

    Returns:
        str: 检测到的格式 (md/json/txt)
    """
    if isinstance(data, str):
        # 检测 Markdown 特征
        if data.strip().startswith("#") or "\n##" in data or "\n###" in data:
            return "md"

        # 检测 CSV 特征 (comma-separated with consistent column count)
        lines = data.strip().splitlines()
        if len(lines) >= 2:
            first_commas = lines[0].count(",")
            if first_commas >= 1 and all(
                line.count(",") == first_commas for line in lines[:5] if line.strip()
            ):
                return "csv"

        # 检测 JSON 字符串
        stripped = data.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                json.loads(data)
                return "json"
            except (json.JSONDecodeError, ValueError):
                pass


        # 检测 Mermaid 特征 (如果包含 graph/flowchart 或 mermaid 代码块)
        if "graph " in data.lower() or "flowchart " in data.lower() or "```mermaid" in data.lower():
            # 如果内容以 # 开头（有标题的 Markdown 包含图表），通常还是用 .md
            # 但如果只有图表，或者用户明确要求，我们应该能识别出这是 mmd 相关内容
            if not (data.strip().startswith("#") or "\n##" in data):
                return "mmd"

        # 默认文本
        return "txt"

    elif isinstance(data, (dict, list)):
        # Python 对象默认JSON
        return "json"

    else:
        # 其他类型转为文本
        return "txt"


def _write_file(filepath: Path, data: Any, format: str) -> None:  # noqa: ANN401
    """
    根据格式写入文件

    Args:
        filepath: 文件路径
        data: 要写入的数据
        format: 文件格式
    """
    if format == "json":
        # JSON格式：结构化输出
        if isinstance(data, (dict, list)):
            content = json.dumps(data, indent=2, ensure_ascii=False)
        elif isinstance(data, str):
            # 如果是JSON字符串，重新格式化
            try:
                obj = json.loads(data)
                content = json.dumps(obj, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                content = data
        else:
            content = json.dumps(str(data), indent=2, ensure_ascii=False)

        filepath.write_text(content, encoding="utf-8")

    elif format == "csv":
        # CSV格式：使用pandas处理
        _write_csv(filepath, data)

    elif format == "yaml":
        # YAML格式：结构化数据
        _write_yaml(filepath, data)

    elif format == "sh":
        # Shell script: write as plain text, ensure LF line endings
        content = str(data)
        filepath.write_text(content, encoding="utf-8", newline="\n")

    else:
        # Markdown/Text/其他
        if format == "md" and isinstance(data, dict):
            content = _dict_to_markdown(data)
        else:
            content = str(data)
        filepath.write_text(content, encoding="utf-8")


def _dict_to_markdown(data: dict[str, Any], level: int = 1) -> str:
    """Recursively convert a dictionary to Markdown headers and lists."""
    lines = []
    for key, val in data.items():
        # Title case the key for headers
        title = str(key).replace("_", " ").title()
        
        if isinstance(val, dict):
            lines.append(f"{'#' * level} {title}")
            lines.append(_dict_to_markdown(val, level + 1))
        elif isinstance(val, list):
            lines.append(f"{'#' * level} {title}")
            for item in val:
                if isinstance(item, dict):
                    # For list of dicts, try to make a table or just nested list
                    lines.append(_dict_to_markdown(item, level + 1))
                else:
                    lines.append(f"- {item}")
        else:
            if level == 1:
                lines.append(f"# {val}" if key == "title" else f"**{title}**: {val}")
            else:
                lines.append(f"- **{title}**: {val}")
        lines.append("")
    return "\n".join(lines)


def _write_csv(filepath: Path, data: Any) -> None:  # noqa: ANN401
    """
    Write CSV file.

    Handles:
    - list[dict] → proper multi-column CSV via pandas/csv
    - JSON string → parse first, then treat as list[dict]
    - dict → single-row CSV
    - Other → fallback to single-column

    Args:
        filepath: File path
        data: Data to write (ideally list[dict] or JSON string of same)
    """
    # Parse JSON strings into native Python objects first
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, (list, dict)):
                data = parsed
        except (json.JSONDecodeError, ValueError):
            pass

    try:
        import pandas as pd

        if isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict):
                df = pd.DataFrame(data)
            else:
                df = pd.DataFrame(data, columns=["value"])
        elif isinstance(data, dict):
            df = pd.DataFrame([data])
        else:
            # Last resort: coerce to string in a single column
            df = pd.DataFrame([{"data": str(data)}])

        df.to_csv(filepath, index=False, encoding="utf-8")

    except ImportError:
        import csv

        with open(filepath, "w", encoding="utf-8", newline="") as f:
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                # Collect ALL unique keys from ALL dicts, not just the first one
                # This handles cases where dicts have different field sets
                all_keys: set[str] = set()
                for row in data:
                    if isinstance(row, dict):
                        all_keys.update(row.keys())
                fieldnames = sorted(all_keys)

                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(data)
            elif isinstance(data, dict):
                writer = csv.DictWriter(f, fieldnames=data.keys())
                writer.writeheader()
                writer.writerow(data)
            else:
                f.write(str(data))


def _write_yaml(filepath: Path, data: Any) -> None:  # noqa: ANN401
    """
    写入YAML文件

    Args:
        filepath: 文件路径
        data: 要写入的数据
    """
    try:
        import yaml

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    except ImportError:
        # yaml未安装，降级为JSON
        content = json.dumps(data, indent=2, ensure_ascii=False)
        filepath.write_text(content, encoding="utf-8")


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    """测试数据导出功能"""

    print("=" * 80)
    print("测试 format_and_export 工具")
    print("=" * 80)

    # 测试1: Markdown报告
    print("\n1️⃣ 测试 Markdown 报告")
    md_content = """# 网络诊断报告

## 问题描述
R1的OSPF邻居down

## 根因分析
子网掩码不匹配

## 解决建议
修改接口IP配置
"""
    result = format_and_export(md_content, filename="test_diagnosis")
    print(f"✅ 导出成功: {result['path']} ({result['size']} bytes)")

    # 测试2: JSON数据
    print("\n2️⃣ 测试 JSON 数据")
    json_data = {
        "devices": [
            {"hostname": "R1", "ip": "192.168.1.1"},
            {"hostname": "R2", "ip": "192.168.1.2"},
        ]
    }
    result = format_and_export(json_data, filename="test_devices")
    print(f"✅ 导出成功: {result['path']} ({result['size']} bytes)")

    # 测试3: 文本输出
    print("\n3️⃣ 测试文本输出")
    text_content = "R1#show tech-support\nCisco IOS Software...\n"
    result = format_and_export(text_content, filename="test_tech_support")
    print(f"✅ 导出成功: {result['path']} ({result['size']} bytes)")

    # 测试4: CSV数据
    print("\n4️⃣ 测试 CSV 导出")
    csv_data = [
        {"vlan_id": 10, "name": "Management", "status": "active"},
        {"vlan_id": 20, "name": "Data", "status": "active"},
        {"vlan_id": 30, "name": "Voice", "status": "inactive"},
    ]
    result = format_and_export(csv_data, filename="test_vlans", format="csv")
    print(f"✅ 导出成功: {result['path']} ({result['size']} bytes)")

    # 测试5: 自动检测
    print("\n5️⃣ 测试自动格式检测")
    auto_data = "## 自动检测测试\n这应该被识别为Markdown"
    result = format_and_export(auto_data)  # 无filename，无format
    print(f"✅ 自动检测并导出: {result['path']} (格式: {result['format']})")

    print("\n" + "=" * 80)
    print("✅ 所有测试通过！检查 exports/ 目录查看导出的文件")
    print("=" * 80)
