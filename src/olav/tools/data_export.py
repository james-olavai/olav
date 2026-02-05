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


def format_and_export(
    data: Any,  # noqa: ANN401
    filename: str | None = None,
    format: str | None = None,
) -> dict[str, Any]:
    """
    导出数据到文件（统一输出到 exports/ 目录）

    Args:
        data: 要导出的数据（字符串/字典/列表/任意对象）
        filename: 文件名（不含扩展名），默认自动生成 export_YYYYmmdd_HHMMSS
        format: 输出格式 (md/json/txt/csv/yaml)，默认自动检测

    Returns:
        dict: {"path": "exports/xxx.md", "size": 1234}

    Examples:
        >>> # 诊断报告（自动检测为Markdown）
        >>> format_and_export("# 诊断报告\\n...", filename="ospf_diagnosis")
        {"path": "exports/ospf_diagnosis.md", "size": 2048}

        >>> # JSON数据（自动检测）
        >>> format_and_export({"devices": [...]}, filename="inventory")
        {"path": "exports/inventory.json", "size": 512}

        >>> # 明确指定格式
        >>> format_and_export(data, filename="vlans", format="csv")
        {"path": "exports/vlans.csv", "size": 256}
    """
    # 1. 统一输出目录
    output_dir = Path("exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2. 自动检测格式（如果未指定）
    if not format:
        format = _detect_format(data)

    # 3. 自动生成文件名（如果未指定）
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{timestamp}"

    # 4. 构建完整路径
    filepath = output_dir / f"{filename}.{format}"

    # 5. 根据格式写入文件
    _write_file(filepath, data, format)

    # 6. 返回结果
    return {
        "path": str(filepath),
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
    写入CSV文件（使用pandas）

    Args:
        filepath: 文件路径
        data: 列表或字典列表
    """
    try:
        import pandas as pd

        # 转换为DataFrame
        if isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict):
                # 字典列表 → DataFrame
                df = pd.DataFrame(data)
            else:
                # 简单列表 → 单列DataFrame
                df = pd.DataFrame(data, columns=["value"])
        elif isinstance(data, dict):
            # 字典 → DataFrame（单行）
            df = pd.DataFrame([data])
        else:
            # 其他类型
            df = pd.DataFrame([{"data": str(data)}])

        # 写入CSV
        df.to_csv(filepath, index=False, encoding="utf-8")

    except ImportError:
        # pandas未安装，降级为简单CSV
        import csv

        content = str(data)
        with open(filepath, "w", encoding="utf-8") as f:
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                # 字典列表
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
            else:
                # 简单数据
                f.write(content)


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
