"""Inspect 报告编排器 - Map-Reduce 模式保证完整性。

v0.9.4 引入：
- Map Phase: 并行处理每个设备 (ReAct Agent)
- Reduce Phase: 汇总报告 + 可选跨设备分析
- 中间文件输出: 可恢复、可调试、可审计
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage


async def inspect_single_device(
    device: str,
    snapshot_date: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """MAP: 单设备 L1-L4 检查 (ReAct Agent)。

    Args:
        device: 设备名称 (e.g., "R1")
        snapshot_date: 快照日期 (YYYY-MM-DD)
        output_dir: 输出目录，None 则不保存中间文件

    Returns:
        设备检查报告 (结构化 JSON)
    """
    from olav.agent import create_olav_agent

    # 创建单设备分析 Agent (不路由，直接查询)
    agent = create_olav_agent(
        enable_skill_routing=False,
        enable_hitl=False,
    )

    # 构建分析提示
    prompt = f"""检查设备 {device} 的 L1-L4 状态。

使用 query_database 工具查询以下数据：
- 数据路径: exports/snapshots/{snapshot_date}/parsed/{device}/

## 检查项目

### L1 (Physical)
- show-version.json: hostname, version, uptime, hardware
- show-environment*.json: temperature, power (如有)

### L2 (Data Link)
- show-ip-interface-brief.json: 接口数量和状态
- show-cdp-neighbors.json 或 show-lldp-neighbors.json: 邻居数

### L3 (Network)
- show-arp.json 或 show-ip-arp.json: ARP 条目数
- show-ip-ospf-neighbor.json: OSPF 邻居状态 (如有)
- show-ip-route.json: 路由数量

### L4 (Transport)
- show-processes-cpu.json: CPU 使用率 (5min)

## 输出格式 (JSON)
严格按此格式输出:
```json
{{
    "device": "{device}",
    "snapshot_date": "{snapshot_date}",
    "l1": {{"version": "版本号", "uptime": "运行时间", "status": "✅|⚠️|❌"}},
    "l2": {{"interfaces_up": N, "interfaces_total": M, "status": "✅|⚠️|❌"}},
    "l3": {{"arp_entries": N, "routes": N, "status": "✅|⚠️|❌"}},
    "l4": {{"cpu_5min": N, "status": "✅|⚠️|❌"}},
    "overall_status": "✅|⚠️|❌",
    "issues": ["问题列表"]
}}
```
"""

    try:
        # 调用 Agent 分析
        result = await agent.ainvoke({"messages": [HumanMessage(content=prompt)]})

        # 解析 Agent 输出
        report = _parse_device_report(result, device, snapshot_date)

        # 保存中间文件
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            device_file = output_dir / f"{device}.json"
            device_file.write_text(json.dumps(report, indent=2, ensure_ascii=False))

        return report

    except Exception as e:
        # 失败时返回错误报告
        error_report = {
            "device": device,
            "snapshot_date": snapshot_date,
            "analyzed_at": datetime.now().isoformat(),
            "l1": {"status": "❌", "error": str(e)},
            "l2": {"status": "❌"},
            "l3": {"status": "❌"},
            "l4": {"status": "❌"},
            "overall_status": "❌",
            "issues": [f"Analysis failed: {e}"],
        }
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / f"{device}.json").write_text(
                json.dumps(error_report, indent=2, ensure_ascii=False)
            )
        return error_report


async def inspect_all_devices(
    devices: list[str] | None = None,
    snapshot_date: str | None = None,
    parallel: bool = True,
    save_intermediate: bool = True,
) -> str:
    """ORCHESTRATOR: 完整的多设备检查 (Map-Reduce)。

    Args:
        devices: 设备列表，None 表示所有设备
        snapshot_date: 快照日期，None 表示最新
        parallel: 是否并行处理
        save_intermediate: 是否保存中间 JSON 文件

    Returns:
        完整的 Markdown 报告
    """
    # 获取设备列表
    if devices is None:
        devices = _get_device_list()

    if snapshot_date is None:
        snapshot_date = _get_latest_snapshot_date()

    # 准备输出目录
    if save_intermediate:
        from config.paths import REPORTS_DIR

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = REPORTS_DIR / f"inspection_{timestamp}"
        devices_dir = report_dir / "devices"
        devices_dir.mkdir(parents=True, exist_ok=True)
    else:
        devices_dir = None
        report_dir = None

    # MAP Phase: 并行/串行处理每个设备
    if parallel:
        device_reports = await asyncio.gather(
            *[inspect_single_device(device, snapshot_date, devices_dir) for device in devices],
            return_exceptions=True,  # 单个失败不影响其他
        )
        # 过滤异常
        device_reports = [r for r in device_reports if isinstance(r, dict)]
    else:
        device_reports = []
        for device in devices:
            report = await inspect_single_device(device, snapshot_date, devices_dir)
            device_reports.append(report)

    # REDUCE Phase: 汇总报告
    final_report = _aggregate_reports(device_reports, snapshot_date)

    # 保存最终报告
    if report_dir:
        # 保存汇总 JSON
        summary_file = report_dir / "summary.json"
        summary_file.write_text(
            json.dumps(
                {
                    "snapshot_date": snapshot_date,
                    "total_devices": len(device_reports),
                    "devices": [r["device"] for r in device_reports],
                    "reports": device_reports,
                },
                indent=2,
                ensure_ascii=False,
            )
        )

        # 保存 Markdown 报告
        report_file = report_dir / "report.md"
        report_file.write_text(final_report, encoding="utf-8")

    return final_report


def _parse_device_report(result: object, device: str, snapshot_date: str) -> dict[str, Any]:
    """解析 Agent 输出为结构化报告。

    Args:
        result: Agent 返回结果 (dict 或 object)
        device: 设备名称
        snapshot_date: 快照日期

    Returns:
        结构化报告字典
    """
    # 提取最后一条消息内容
    # Agent 返回 dict {'messages': [...]} 或有 .messages 属性的对象
    if isinstance(result, dict) and "messages" in result and result["messages"]:
        content = result["messages"][-1].content
    elif hasattr(result, "messages") and result.messages:
        content = result.messages[-1].content
    elif hasattr(result, "content"):
        content = result.content
    else:
        content = str(result)

    # 尝试从内容中提取 JSON
    try:
        # 查找 ```json 代码块
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            json_str = content[start:end].strip()
            report = json.loads(json_str)
        elif "```" in content:
            # 尝试提取任意代码块
            start = content.find("```") + 3
            end = content.find("```", start)
            json_str = content[start:end].strip()
            report = json.loads(json_str)
        else:
            # 直接尝试解析整个内容
            report = json.loads(content)

        # 确保必要字段存在
        report.setdefault("device", device)
        report.setdefault("snapshot_date", snapshot_date)
        report.setdefault("analyzed_at", datetime.now().isoformat())

        return report

    except (json.JSONDecodeError, ValueError):
        # 解析失败，返回默认报告
        return {
            "device": device,
            "snapshot_date": snapshot_date,
            "analyzed_at": datetime.now().isoformat(),
            "l1": {"status": "⚠️", "note": "Unable to parse analysis"},
            "l2": {"status": "⚠️"},
            "l3": {"status": "⚠️"},
            "l4": {"status": "⚠️"},
            "overall_status": "⚠️",
            "issues": ["Failed to parse agent response"],
            "raw_output": content[:500],  # 保留前500字符用于调试
        }


def _aggregate_reports(reports: list[dict], snapshot_date: str) -> str:
    """REDUCE: 汇总设备报告为 Markdown。

    Args:
        reports: 设备报告列表
        snapshot_date: 快照日期

    Returns:
        Markdown 格式报告
    """
    lines = [
        "# Network Inspection Report",
        "",
        f"**Date:** {snapshot_date}",
        f"**Devices:** {len(reports)}",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        "",
        "| Device | Version | L1 | L2 | L3 | L4 | Status |",
        "|--------|---------|----|----|----|----|--------|",
    ]

    # 汇总表格
    for r in sorted(reports, key=lambda x: x.get("device", "")):
        device = r.get("device", "Unknown")
        version = r.get("l1", {}).get("version", "N/A")
        l1_status = r.get("l1", {}).get("status", "⚠️")
        l2_status = r.get("l2", {}).get("status", "⚠️")
        l3_status = r.get("l3", {}).get("status", "⚠️")
        l4_status = r.get("l4", {}).get("status", "⚠️")
        overall = r.get("overall_status", "⚠️")

        lines.append(
            f"| {device} | {version} | {l1_status} | {l2_status} | {l3_status} | {l4_status} | {overall} |"
        )

    # 设备详情
    lines.extend(["", "## Device Details", ""])

    for r in sorted(reports, key=lambda x: x.get("device", "")):
        device = r.get("device", "Unknown")
        lines.extend([f"### {device}", ""])

        # L1 Physical
        l1 = r.get("l1", {})
        lines.append(f"**L1 Physical**: {l1.get('status', '⚠️')}")
        if "version" in l1:
            lines.append(f"- Version: {l1['version']}")
        if "uptime" in l1:
            lines.append(f"- Uptime: {l1['uptime']}")
        if "hardware" in l1:
            lines.append(f"- Hardware: {l1['hardware']}")
        lines.append("")

        # L2 Data Link
        l2 = r.get("l2", {})
        lines.append(f"**L2 Data Link**: {l2.get('status', '⚠️')}")
        if "interfaces_up" in l2 and "interfaces_total" in l2:
            lines.append(f"- Interfaces: {l2['interfaces_up']}/{l2['interfaces_total']} up")
        if "cdp_neighbors" in l2:
            lines.append(f"- CDP Neighbors: {l2['cdp_neighbors']}")
        lines.append("")

        # L3 Network
        l3 = r.get("l3", {})
        lines.append(f"**L3 Network**: {l3.get('status', '⚠️')}")
        if "arp_entries" in l3:
            lines.append(f"- ARP Entries: {l3['arp_entries']}")
        if "routes" in l3:
            lines.append(f"- Routes: {l3['routes']}")
        if "ospf_neighbors" in l3:
            neighbors = l3["ospf_neighbors"]
            if isinstance(neighbors, list):
                lines.append(f"- OSPF Neighbors: {len(neighbors)}")
        lines.append("")

        # L4 Transport
        l4 = r.get("l4", {})
        lines.append(f"**L4 Transport**: {l4.get('status', '⚠️')}")
        if "cpu_5min" in l4:
            lines.append(f"- CPU (5min): {l4['cpu_5min']}%")
        if "memory_used_pct" in l4:
            lines.append(f"- Memory: {l4['memory_used_pct']}%")
        lines.append("")

        # Issues
        issues = r.get("issues", [])
        if issues:
            lines.append("**Issues:**")
            for issue in issues:
                lines.append(f"- ⚠️ {issue}")
            lines.append("")

    return "\n".join(lines)


def _get_device_list() -> list[str]:
    """从 Nornir 配置获取设备列表。"""
    from olav.tools.network_executor import get_nornir

    try:
        nr = get_nornir()
        return list(nr.inventory.hosts.keys())
    except Exception:
        # 降级：从快照目录读取
        from config.paths import SNAPSHOTS_LATEST_DIR

        if SNAPSHOTS_LATEST_DIR.exists():
            parsed_dir = SNAPSHOTS_LATEST_DIR / "parsed"
            if parsed_dir.exists():
                return [d.name for d in parsed_dir.iterdir() if d.is_dir()]
        return []


def _get_latest_snapshot_date() -> str:
    """获取最新快照日期。"""
    from config.paths import SNAPSHOTS_DIR

    if not SNAPSHOTS_DIR.exists():
        return datetime.now().strftime("%Y-%m-%d")

    # 查找最新日期目录
    date_dirs = [d for d in SNAPSHOTS_DIR.iterdir() if d.is_dir() and d.name != "latest"]
    if date_dirs:
        latest = max(date_dirs, key=lambda d: d.name)
        return latest.name

    return datetime.now().strftime("%Y-%m-%d")
