"""Skill-controlled Markdown report formatter.

This module provides functionality to generate formatted reports in Markdown
based on skill frontmatter configuration.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

# Language strings for multilingual support
LANG_STRINGS: dict[str, dict[str, str]] = {
    "en-US": {
        "title": "Inspection Report",
        "time": "Inspection Time",
        "devices": "Total Devices",
        "summary": "Summary",
        "device": "Device",
        "status": "Status",
        "details": "Details",
        "command": "Command",
        "result": "Result",
        "recommendations": "Recommendations",
        "no_issues": "No issues found",
        "issues_found": "Issues Found",
    },
    "zh-CN": {
        "title": "巡检报告",
        "time": "巡检时间",
        "devices": "设备总数",
        "summary": "摘要",
        "device": "设备",
        "status": "状态",
        "details": "详情",
        "command": "命令",
        "result": "结果",
        "recommendations": "建议",
        "no_issues": "未发现问题",
        "issues_found": "发现的问题",
    },
}


def format_inspection_report(
    results: dict[str, list[dict[str, Any]]],
    skill_config: dict[str, Any],
    inspection_type: str = "Network Inspection",
) -> str:
    """Generate Markdown report based on skill output configuration.

    Args:
        results: Raw inspection results from nornir_bulk_execute.
            Format: {device_name: [result1, result2, ...]}
        skill_config: Skill frontmatter with output configuration.
            Expected keys:
                - output.format: "markdown" | "json" | "table"
                - output.language: "zh-CN" | "en-US" | "auto"
                - output.sections: list of sections to include
        inspection_type: Type of inspection (e.g., "L1-L4 Inspection", "Health Check")

    Returns:
        Formatted report string in Markdown format.

    Examples:
        >>> skill_config = {
        ...     "output": {
        ...         "format": "markdown",
        ...         "language": "en-US",
        ...         "sections": ["summary", "details"]
        ...     }
        ... }
        >>> results = {"R1": [{"command": "show version", "success": True, "output": "..."}]}
        >>> report = format_inspection_report(results, skill_config)
        >>> print(report)
        # Inspection Report
        ...
    """
    output_config = skill_config.get("output", {})
    lang = _resolve_language(output_config.get("language", "auto"))
    sections = output_config.get("sections", ["summary", "details"])

    strings = LANG_STRINGS.get(lang, LANG_STRINGS["en-US"])

    lines = []

    # Header
    lines.append(f"# {strings['title']}")
    lines.append("")
    lines.append(f"**{strings['time']}**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Type**: {inspection_type}")
    lines.append(f"**{strings['devices']}**: {len(results)}")
    lines.append("")

    # Summary section
    if "summary" in sections:
        lines.append(_format_summary(results, strings))
        lines.append("")

    # Details section
    if "details" in sections:
        lines.append(_format_details(results, strings))
        lines.append("")

    # Recommendations section
    if "recommendations" in sections:
        lines.append(_format_recommendations(results, strings, lang))
        lines.append("")

    return "\n".join(lines)


def _resolve_language(language: str) -> str:
    """Resolve 'auto' language to actual language code.

    Language is controlled by Skill YAML frontmatter:
    ```yaml
    output:
      language: auto  # or 'en-US', 'zh-CN'
    ```

    The 'auto' setting lets the LLM detect and adapt to user's language.
    This function provides a fallback default only.

    Args:
        language: Language code from Skill config ("auto", "en-US", "zh-CN")

    Returns:
        Resolved language code ("en-US" or "zh-CN")
    """
    if language == "auto":
        # Default to English when auto-detection is requested
        # LLM will adapt based on user's input language in Skill execution
        return "en-US"
    return language


def _format_summary(results: dict[str, list[dict[str, Any]]], strings: dict[str, str]) -> str:
    """Format the summary section of the report.

    Args:
        results: Inspection results by device
        strings: Localized strings dictionary

    Returns:
        Markdown formatted summary table
    """
    lines = []
    lines.append(f"## {strings['summary']}")
    lines.append("")
    lines.append(f"| {strings['device']} | {strings['status']} | Success | Errors |")
    lines.append("|--------|--------|---------|--------|")

    total_success = 0
    total_errors = 0

    for device, device_results in results.items():
        success_count = sum(1 for r in device_results if r.get("success"))
        error_count = len(device_results) - success_count
        total_success += success_count
        total_errors += error_count

        # Status emoji based on success rate
        if error_count == 0:
            status = "✅"
        elif success_count > 0:
            status = "⚠️"
        else:
            status = "❌"

        lines.append(
            f"| {device} | {status} | {success_count}/{len(device_results)} | {error_count} |"
        )

    # Overall status
    overall_status = "✅" if total_errors == 0 else ("⚠️" if total_success > 0 else "❌")
    lines.append("")
    lines.append(f"**Overall Status**: {overall_status}")
    lines.append(f"**Total Commands**: {total_success + total_errors}")
    lines.append(f"**Successful**: {total_success}")
    lines.append(f"**Failed**: {total_errors}")

    return "\n".join(lines)


def _format_details(results: dict[str, list[dict[str, Any]]], strings: dict[str, str]) -> str:
    """Format the detailed results section of the report.

    Args:
        results: Inspection results by device
        strings: Localized strings dictionary

    Returns:
        Markdown formatted details section
    """
    lines = []
    lines.append(f"## {strings['details']}")
    lines.append("")

    for device, device_results in results.items():
        lines.append(f"### {device}")
        lines.append("")

        for result in device_results:
            cmd = result.get("command", "unknown")

            if result.get("success"):
                lines.append(f"**`{cmd}`** ✅")
                output = result.get("output", "")

                # Truncate long output
                if len(output) > 1000:
                    output = output[:1000] + "\n\n... (truncated)"

                lines.append("```")
                lines.append(output)
                lines.append("```")
            else:
                error = result.get("error", "Unknown error")
                lines.append(f"**`{cmd}`** ❌")
                lines.append(f"Error: {error}")

            lines.append("")

    return "\n".join(lines)


def _format_recommendations(
    results: dict[str, list[dict[str, Any]]],
    strings: dict[str, str],
    lang: str,
) -> str:
    """Generate recommendations based on inspection results.

    Args:
        results: Inspection results by device
        strings: Localized strings dictionary
        lang: Language code for output

    Returns:
        Markdown formatted recommendations section
    """
    lines = []
    lines.append(f"## {strings['recommendations']}")
    lines.append("")

    issues = []

    # Collect issues from results
    for device, device_results in results.items():
        for result in device_results:
            if not result.get("success"):
                cmd = result.get("command", "unknown")
                error = result.get("error", "Unknown error")
                issues.append(f"{device}: {cmd} failed - {error}")

    if issues:
        lines.append(f"### {strings['issues_found']}: {len(issues)}")
        lines.append("")

        for i, issue in enumerate(issues, 1):
            lines.append(f"{i}. {issue}")

        lines.append("")
        lines.append("**Suggested Actions**:")
        lines.append("")
        lines.append("1. Review failed commands and error messages")
        lines.append("2. Check device connectivity and credentials")
        lines.append("3. Verify command syntax for the specific platform")
        lines.append("4. Re-run inspection after fixing issues")
    else:
        lines.append(f"### {strings['no_issues']}")
        lines.append("")
        lines.append("All devices are functioning normally. No immediate action required.")

    return "\n".join(lines)


def format_json_report(
    results: dict[str, list[dict[str, Any]]], skill_config: dict[str, Any]
) -> str:
    """Generate JSON format report.

    Args:
        results: Raw inspection results
        skill_config: Skill configuration

    Returns:
        JSON formatted string
    """
    import json

    report = {
        "timestamp": datetime.now().isoformat(),
        "total_devices": len(results),
        "devices": {},
    }

    for device, device_results in results.items():
        success_count = sum(1 for r in device_results if r.get("success"))
        report["devices"][device] = {
            "total_commands": len(device_results),
            "successful": success_count,
            "failed": len(device_results) - success_count,
            "results": device_results,
        }

    return json.dumps(report, indent=2, ensure_ascii=False)


def format_table_report(
    results: dict[str, list[dict[str, Any]]], skill_config: dict[str, Any]
) -> str:
    """Generate simple table format report.

    Args:
        results: Raw inspection results
        skill_config: Skill configuration

    Returns:
        Table formatted string
    """
    lang = _resolve_language(skill_config.get("output", {}).get("language", "auto"))
    strings = LANG_STRINGS.get(lang, LANG_STRINGS["en-US"])

    lines = []
    lines.append(f"| {strings['device']} | {strings['status']} | Commands | Success | Failed |")
    lines.append("|--------|--------|----------|---------|--------|")

    for device, device_results in results.items():
        success_count = sum(1 for r in device_results if r.get("success"))
        fail_count = len(device_results) - success_count

        status = "✅" if fail_count == 0 else ("⚠️" if success_count > 0 else "❌")

        lines.append(
            f"| {device} | {status} | {len(device_results)} | {success_count} | {fail_count} |"
        )

    return "\n".join(lines)


def format_report(
    results: dict[str, list[dict[str, Any]]],
    skill_config: dict[str, Any],
    inspection_type: str = "Network Inspection",
) -> str:
    """Main entry point for report formatting.

    Selects the appropriate formatter based on output configuration.

    Args:
        results: Raw inspection results
        skill_config: Skill frontmatter configuration
        inspection_type: Type of inspection being performed

    Returns:
        Formatted report string
    """
    output_config = skill_config.get("output", {})
    output_format = output_config.get("format", "markdown")

    if output_format == "json":
        return format_json_report(results, skill_config)
    elif output_format == "table":
        return format_table_report(results, skill_config)
    else:  # markdown (default)
        return format_inspection_report(results, skill_config, inspection_type)


# =============================================================================
# Network Operations Report Generator (for sync_tools Stage 2)
# =============================================================================


def generate_professional_inspection_report(
    metadata: dict[str, Any],
    anomalies: dict[str, list[dict[str, Any]]],
    llm_analysis: dict[str, Any],
    layers_config: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a production-grade, professional network inspection report.

    This creates a comprehensive inspection report with:
    - Executive Overview with health score
    - Inspection Scope & Methodology
    - L1-L4 Layer Analysis with expected vs actual states
    - Device Status Matrix
    - Issue Analysis with root cause and impact
    - Actionable Recommendations with priorities and steps
    - Next Steps with specific commands

    Args:
        metadata: Inspection metadata (timestamp, device_count, all_devices, inspection_type)
        anomalies: Device anomalies: {device: [{metric, severity, value, threshold, ...}]}
        llm_analysis: LLM global analysis: {root_cause, impact, recommendations}
        layers_config: Optional layer configuration from skill

    Returns:
        Professional markdown report string
    """
    lines = []

    # =========================================================================
    # 1. HEADER & EXECUTIVE SUMMARY
    # =========================================================================
    lines.append("# 🔍 Network Health Inspection Report")
    lines.append("")
    lines.append(f"**Inspection Time**: {metadata['timestamp']}")
    inspection_type = metadata.get("inspection_type", "manual")
    type_label = "📅 Scheduled" if inspection_type == "scheduled" else "👤 Manual"
    lines.append(f"**Type**: {type_label}")
    lines.append(f"**Devices Inspected**: {metadata['device_count']}")
    lines.append("")

    # Calculate overall status
    total_devices = metadata["device_count"]
    critical_count = sum(
        1 for d in anomalies.values() if any(a["severity"] == "critical" for a in d)
    )
    warning_count = sum(
        1
        for d in anomalies.values()
        if any(a["severity"] == "warning" for a in d)
        and not any(a["severity"] == "critical" for a in d)
    )
    normal_count = total_devices - critical_count - warning_count

    # Load scoring configuration from SKILL or settings
    from config.settings import settings
    from olav.core.skill_loader import get_skill_loader

    loader = get_skill_loader()
    inspection_skill = loader.get_skill("network-inspection")
    scoring_config = inspection_skill.frontmatter.get("scoring", {}) if inspection_skill else {}

    if not scoring_config:
        # Fall back to settings if SKILL config not found
        health_config = settings.health_score_config
        critical_weight = health_config["critical_weight"]
        warning_weight = health_config["warning_weight"]
        max_score = health_config["max_score"]
        thresholds = health_config["thresholds"]
    else:
        critical_weight = scoring_config.get("critical_weight", 20)
        warning_weight = scoring_config.get("warning_weight", 5)
        max_score = scoring_config.get("max_score", 100)
        thresholds = scoring_config.get("thresholds", {"healthy": 90, "warning": 70, "critical": 0})

    # Health score calculation (now configurable via SKILL or settings)
    health_score = max_score - (critical_count * critical_weight + warning_count * warning_weight)
    health_score = max(0, min(max_score, health_score))

    # Determine health status based on configurable thresholds
    if health_score >= thresholds.get("healthy", 90):
        health_status = "✅ HEALTHY"
        health_color = "green"
    elif health_score >= thresholds.get("warning", 70):
        health_status = "⚠️ WARNING"
        health_color = "yellow"
    else:
        health_status = "🔴 CRITICAL"
        health_color = "red"

    lines.append("## 📊 Executive Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Overall Health Score | **{health_score}%** {health_status} |")
    lines.append(f"| Normal Devices | {normal_count}/{total_devices} ✅ |")
    lines.append(f"| Warning Devices | {warning_count}/{total_devices} ⚠️ |")
    lines.append(f"| Critical Devices | {critical_count}/{total_devices} 🔴 |")
    lines.append("")

    lines.append(llm_analysis.get("impact", "Network status under review."))
    lines.append("")

    # =========================================================================
    # 2. INSPECTION SCOPE & METHODOLOGY
    # =========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## 🎯 Inspection Scope & Methodology")
    lines.append("")
    lines.append("### What Was Checked (检查项目)")
    lines.append("")
    lines.append("This inspection covered **L1-L4 multi-layer analysis**:")
    lines.append("")
    lines.append("| Layer | Scope | Items Checked |")
    lines.append("|-------|-------|---------------|")
    lines.append(
        "| **L1 Physical** | Device Health | Uptime, CPU, Memory, Temperature, Power Supply, Fans |"
    )
    lines.append(
        "| **L2 DataLink** | Interface Status | Interface State, Errors, Drops, VLAN, STP |"
    )
    lines.append(
        "| **L3 Network** | Routing Health | Route Table, OSPF Neighbors, BGP Sessions, VPN Status |"
    )
    lines.append(
        "| **L4 Application** | Service Status | Protocol Sessions, Queue Depth, Service Health |"
    )
    lines.append("")

    # =========================================================================
    # 3. DEVICE STATUS MATRIX
    # =========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## 📱 Device Status Matrix")
    lines.append("")
    lines.append("### Per-Device L1-L4 Status")
    lines.append("")
    lines.append("| Device | L1 Physical | L2 DataLink | L3 Network | L4 Application | Overall |")
    lines.append("|--------|-------------|------------|-----------|----------------|---------|")

    for device in sorted(metadata["all_devices"]):
        device_anomalies = anomalies.get(device, [])

        # Determine layer status
        layer_status = {"L1": "✅", "L2": "✅", "L3": "✅", "L4": "✅"}
        for anomaly in device_anomalies:
            layer = anomaly.get("layer", "L4")
            for l in ["L1", "L2", "L3", "L4"]:
                if l in layer:
                    if anomaly["severity"] == "critical":
                        layer_status[l] = "🔴"
                    elif anomaly["severity"] == "warning" and layer_status[l] == "✅":
                        layer_status[l] = "⚠️"

        # Overall device status
        if any(a["severity"] == "critical" for a in device_anomalies):
            overall = "🔴 Critical"
        elif any(a["severity"] == "warning" for a in device_anomalies):
            overall = "⚠️ Warning"
        else:
            overall = "✅ Normal"

        lines.append(
            f"| {device} | {layer_status['L1']} | {layer_status['L2']} | "
            f"{layer_status['L3']} | {layer_status['L4']} | {overall} |"
        )

    lines.append("")

    # =========================================================================
    # 4. EXPECTED vs ACTUAL STATE
    # =========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## 📋 Expected vs Actual State Analysis")
    lines.append("")

    if anomalies:
        # Group by severity
        critical_issues = []
        warning_issues = []

        for device, device_anomalies in anomalies.items():
            for anomaly in device_anomalies:
                if anomaly["severity"] == "critical":
                    critical_issues.append((device, anomaly))
                else:
                    warning_issues.append((device, anomaly))

        # Critical issues
        if critical_issues:
            lines.append("### 🔴 Critical Issues")
            lines.append("")
            for device, issue in critical_issues:
                lines.append(
                    f"**{device} - {issue.get('metric', 'Unknown')}** [{issue.get('layer', 'L4')}]"
                )
                lines.append("")
                lines.append(f"- **Expected State**: {issue.get('threshold', 'Normal')} or better")
                lines.append(f"- **Actual State**: {issue.get('value', 'N/A')}")
                lines.append("- **Severity**: 🔴 CRITICAL")
                if issue.get("detail"):
                    lines.append(f"- **Details**: {issue['detail']}")
                lines.append("")

        # Warning issues
        if warning_issues:
            lines.append("### ⚠️ Warning Issues")
            lines.append("")
            for device, issue in warning_issues:
                lines.append(
                    f"**{device} - {issue.get('metric', 'Unknown')}** [{issue.get('layer', 'L4')}]"
                )
                lines.append("")
                lines.append(f"- **Expected State**: {issue.get('threshold', 'Normal')} or better")
                lines.append(f"- **Actual State**: {issue.get('value', 'N/A')}")
                lines.append("- **Severity**: ⚠️ WARNING")
                if issue.get("detail"):
                    lines.append(f"- **Details**: {issue['detail']}")
                lines.append("")
    else:
        lines.append(
            "✅ **No anomalies detected** - All devices are operating within expected parameters."
        )
        lines.append("")

    # =========================================================================
    # 5. ROOT CAUSE & IMPACT ANALYSIS
    # =========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## 🔎 Root Cause & Impact Analysis")
    lines.append("")

    lines.append("### Root Cause Analysis")
    lines.append("")
    lines.append(llm_analysis.get("root_cause", "No root cause identified."))
    lines.append("")

    lines.append("### Business Impact Assessment")
    lines.append("")
    lines.append(llm_analysis.get("impact", "No significant impact identified."))
    lines.append("")

    # =========================================================================
    # 6. RECOMMENDATIONS WITH ACTION STEPS
    # =========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## 💡 Recommendations & Action Plan")
    lines.append("")

    recommendations = llm_analysis.get("recommendations", [])

    if recommendations:
        # Immediate actions (critical priority)
        immediate = [r for r in recommendations if r.get("priority") == "critical"]
        if immediate:
            lines.append("### 🚨 Immediate Actions Required")
            lines.append("")
            for i, rec in enumerate(immediate, 1):
                lines.append(f"**Step {i}**: {rec.get('action', 'Action')}")
                lines.append("")

        # Planned actions (warning priority)
        planned = [r for r in recommendations if r.get("priority") == "warning"]
        if planned:
            lines.append("### 📅 Planned Actions")
            lines.append("")
            for i, rec in enumerate(planned, 1):
                lines.append(f"**Step {i}**: {rec.get('action', 'Action')}")
                lines.append("")

        # Optimization (info priority)
        optimization = [r for r in recommendations if r.get("priority") == "info"]
        if optimization:
            lines.append("### 🔧 Optimization Suggestions")
            lines.append("")
            for i, rec in enumerate(optimization, 1):
                lines.append(f"**Step {i}**: {rec.get('action', 'Action')}")
                lines.append("")
    else:
        lines.append("✅ No actions required at this time. Continue routine monitoring.")
        lines.append("")

    # =========================================================================
    # 7. NEXT STEPS WITH COMMANDS
    # =========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## 📞 Next Steps")
    lines.append("")
    lines.append("### Follow-up Commands")
    lines.append("")
    lines.append("To perform deeper analysis or monitor specific issues, use these commands:")
    lines.append("")
    lines.append("```bash")
    lines.append("# Query inspection database for specific device")
    lines.append("olav query --inspection --device <device_name>")
    lines.append("")
    lines.append("# Search for specific metric anomalies")
    lines.append("olav search --metric <metric_name> --severity critical")
    lines.append("")
    lines.append("# Compare current vs previous inspection")
    lines.append("olav inspect --compare-baseline")
    lines.append("")
    lines.append("# Run focused inspection on specific layer")
    lines.append("olav inspect --layer L1 --device-group test")
    lines.append("")
    lines.append("# Export detailed report for analysis")
    lines.append("olav export --inspection --format json > inspection_$(date +%Y%m%d).json")
    lines.append("```")
    lines.append("")

    # =========================================================================
    # 8. FOOTER
    # =========================================================================
    lines.append("---")
    lines.append("")
    lines.append("**Report Generated**: OLAV v0.9.8 - Professional Network Health Inspector")
    lines.append(f"**Timestamp**: {metadata['timestamp']}")
    lines.append("")

    return "\n".join(lines)


def generate_network_operations_report(
    sync_dir: Path, device_names: list[str], success_devices: int = None, failed_devices: int = None
) -> None:
    """Generate comprehensive network operations analysis report.

    This is called from sync_tools Stage 2 after data collection and parsing.
    Creates a single YYYYMMDD.md report in exports/reports/.

    Args:
        sync_dir: Path to sync directory (e.g., /data/sync/2026-01-14)
        device_names: List of device names that were synced
        success_devices: Number of successfully inspected devices
        failed_devices: Number of failed device inspections
    """

    try:
        # Calculate basic stats from raw data
        total_devices = len(device_names)
        total_files = 0
        for device_dir in (sync_dir / "raw").iterdir():
            if device_dir.is_dir():
                total_files += len(list(device_dir.glob("*.txt")))

        # Build report with enhanced sections
        lines = []
        lines.append("# Network Snapshot Report")
        lines.append("")
        lines.append(f"**Report Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Snapshot Date**: {sync_dir.name}")
        lines.append("")

        # Inspection execution statistics
        if success_devices is not None or failed_devices is not None:
            total_inspected = (success_devices or 0) + (failed_devices or 0)
            lines.append("## 📊 Inspection Execution Summary")
            lines.append("")
            lines.append("| Metric | Count |")
            lines.append("|--------|-------|")
            lines.append(f"| Total Devices | {total_devices} |")
            lines.append(f"| Successfully Inspected | {success_devices or 0} |")
            lines.append(f"| Failed Inspection | {failed_devices or 0} |")
            lines.append(
                f"| Success Rate | {(success_devices or 0) * 100 // total_inspected if total_inspected > 0 else 0}% |"
            )
            lines.append("")

        lines.append(f"**Total Command Outputs Collected**: {total_files}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Device inventory
        lines.append("## 📱 Device Inventory")
        lines.append("")
        lines.append("| Device | Status |")
        lines.append("|--------|--------|")
        for device in sorted(device_names):
            lines.append(f"| {device} | ✅ Active |")
        lines.append("")

        # Try to query database for enhanced data
        try:
            # Import here to ensure database is properly initialized
            import time

            from olav.core.unified_database import UnifiedDatabase

            # Retry logic for database connection
            max_retries = 3
            db = None
            for attempt in range(max_retries):
                try:
                    db = UnifiedDatabase()
                    # Test connection
                    test = db.query("SELECT COUNT(*) FROM raw_outputs")
                    if test:
                        break
                except Exception:
                    if attempt < max_retries - 1:
                        time.sleep(0.5)
                    else:
                        raise

            if not db:
                raise Exception("Failed to connect to database after retries")

            # Interfaces section
            lines.append("## 🔌 Interfaces Summary")
            lines.append("")
            try:
                interfaces = db.query(
                    """SELECT device, COUNT(*) as count FROM raw_outputs 
                       WHERE command LIKE '%interface%' OR command LIKE '%int%brief%' 
                       GROUP BY device ORDER BY device"""
                )
                if interfaces and len(interfaces) > 0:
                    lines.append("| Device | Interface Commands |")
                    lines.append("|--------|-------------------|")
                    total_interfaces = 0
                    for device, count in interfaces:
                        lines.append(f"| {device} | {count} |")
                        total_interfaces += count
                    lines.append(f"\n**Total**: {total_interfaces} interface-related commands\n")
                else:
                    lines.append("*No interface-specific commands captured*\n")
            except Exception:
                lines.append("*Note: Could not retrieve interface data*\n")

            # Routing section
            lines.append("## 🛣️ Routing Summary")
            lines.append("")
            try:
                routes = db.query(
                    """SELECT device, COUNT(*) as count FROM raw_outputs 
                       WHERE command LIKE '%route%' OR command LIKE '%ip route%' 
                       GROUP BY device ORDER BY device"""
                )
                if routes and len(routes) > 0:
                    lines.append("| Device | Routing Commands |")
                    lines.append("|--------|------------------|")
                    total_routes = 0
                    for device, count in routes:
                        lines.append(f"| {device} | {count} |")
                        total_routes += count
                    lines.append(f"\n**Total**: {total_routes} routing commands\n")
                else:
                    lines.append("*No routing-specific commands captured*\n")
            except Exception:
                lines.append("*Note: Could not retrieve routing data*\n")

            # Protocol section (BGP, OSPF, etc)
            lines.append("## 📡 Protocol Summary")
            lines.append("")
            try:
                # BGP summary
                bgp = db.query(
                    "SELECT device, COUNT(*) as count FROM raw_outputs WHERE command LIKE '%bgp%' GROUP BY device ORDER BY device"
                )
                # OSPF summary
                ospf = db.query(
                    "SELECT device, COUNT(*) as count FROM raw_outputs WHERE command LIKE '%ospf%' GROUP BY device ORDER BY device"
                )

                has_data = False
                if bgp and len(bgp) > 0:
                    lines.append("**BGP Adjacencies:**")
                    for device, count in bgp:
                        lines.append(f"- {device}: {count} BGP-related commands")
                    has_data = True

                if ospf and len(ospf) > 0:
                    if has_data:
                        lines.append("")
                    lines.append("**OSPF Adjacencies:**")
                    for device, count in ospf:
                        lines.append(f"- {device}: {count} OSPF-related commands")
                    has_data = True

                if not has_data:
                    lines.append("*No protocol-specific data captured*")

                lines.append("")
            except Exception:
                lines.append("*Note: Could not retrieve protocol data*\n")

        except Exception:
            lines.append(
                "## 📊 Data Status\n\nReport enhancement in progress - partial data captured.\n\n"
            )

        # Data collection summary
        lines.append("## 📁 Data Collection Summary")
        lines.append("")
        lines.append(f"- **Raw Command Outputs**: {total_files} files")
        lines.append(f"- **Storage Location**: `{sync_dir}`")
        lines.append("- **Database**: Available for detailed queries")
        lines.append("")

        # Recommendations
        lines.append("## 💡 Next Steps")
        lines.append("")
        lines.append("1. Query collected data using `query_sync_db()`")
        lines.append("2. Search specific patterns using `search_sync()`")
        lines.append("3. Compare configs using `diff_configs()`")
        lines.append("4. Run `/inspect` for anomaly detection")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("*Auto-generated by OLAV v0.9.8*")
        lines.append("")

        # Write report to exports/reports/YYYYMMDD.md
        from config.paths import REPORTS_DIR

        sync_date = sync_dir.name  # YYYY-MM-DD
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_filename = sync_date.replace("-", "") + ".md"
        report_file = REPORTS_DIR / report_filename
        report_file.write_text("\n".join(lines), encoding="utf-8")

    except Exception as e:
        # Report generation is optional, log error but don't fail
        import logging

        logging.warning(f"Failed to generate operations report: {e}")
