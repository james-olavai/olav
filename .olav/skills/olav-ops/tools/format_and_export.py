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
    data: Any,  # noqa: ANN401
    filename: str | None = None,
    format: str | None = None,
) -> dict[str, Any]:
    """
    Export data to file (unified output to exports/ directory).

    CRITICAL: For CSV/JSON export, pass the RAW structured data from
    query_database tool results — the JSON array of objects, NOT a text
    summary or markdown table. This ensures proper tabular output.

    Args:
        data: Data to export. For CSV: MUST be a JSON array of objects
              (e.g. [{"hostname": "R1", "ip": "10.0.0.1"}, ...]).
              For markdown/text: can be a formatted string.
        filename: Filename (without extension), auto-generated if omitted
        format: Output format (md/json/txt/csv/yaml), auto-detected if omitted

    Returns:
        dict: {"path": "exports/xxx.csv", "size": 1234}

    Examples:
        >>> # CSV export — pass raw JSON data from query_database
        >>> format_and_export(
        ...     '[{"hostname": "R1", "ip": "10.0.0.1"}, {"hostname": "R2", "ip": "10.0.0.2"}]',
        ...     filename="devices", format="csv"
        ... )
        {"path": "exports/devices.csv", "size": 256}

        >>> # Diagnosis report (auto-detected as Markdown)
        >>> format_and_export("# Diagnosis Report\n...", filename="ospf_diagnosis")
        {"path": "exports/reports/ospf_diagnosis.md", "size": 2048}
    """
    # 1. Determine output directory based on format
    from config.paths import REPORTS_DIR
    
    if format and format.lower() in ("csv", "json", "yaml", "yml"):
        output_dir = REPORTS_DIR.parent  # exports/
    elif format and format.lower() in ("md", "txt"):
        output_dir = REPORTS_DIR  # exports/reports/
    else:
        output_dir = None  # resolved after format detection

    # 2. Parse JSON strings into native Python objects.
    #    LLM tool calls often pass query_database results as JSON strings.
    #    Converting early ensures _detect_format and _write_csv see list[dict].
    if isinstance(data, str):
        stripped = data.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, (list, dict)):
                    data = parsed
            except (json.JSONDecodeError, ValueError):
                pass

    # 3. Auto-detect format (if not specified)
    if not format:
        format = _detect_format(data)

    # 4. Resolve output_dir if not yet determined
    if output_dir is None:
        from config.paths import REPORTS_DIR as _REPORTS_DIR
        if format in ("csv", "json", "yaml", "yml"):
            output_dir = _REPORTS_DIR.parent  # exports/
        else:
            output_dir = _REPORTS_DIR  # exports/reports/

    output_dir.mkdir(parents=True, exist_ok=True)

    # 5. Auto-generate filename (if not specified)
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{timestamp}"
    
    # Sanitize filename to prevent path traversal (security fix)
    # Remove path separators and parent directory references
    from pathlib import PurePath
    filename = PurePath(filename).name  # Extract only the filename component
    if ".." in filename or filename.startswith("/"):
        raise ValueError(f"Invalid filename: {filename}. Cannot contain '..' or start with '/'")

    # 6. Build full path
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

    else:
        # Markdown/Text/其他：直接写入
        content = str(data)
        filepath.write_text(content, encoding="utf-8")


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
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
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
