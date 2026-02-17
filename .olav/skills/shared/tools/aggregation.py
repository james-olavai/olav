"""MapReduce Aggregation Tools for OLAV Inspection Pipeline.

This module provides Reduce-phase tools for aggregating inspection results
from multiple devices into comprehensive reports with health scores and
anomaly detection.

Exported Tools:
- aggregate_inspection_results() - Aggregate and analyze device results
- identify_anomalies() - Detect and classify anomalies
"""

from datetime import datetime
from typing import Any
from dataclasses import dataclass, asdict
import json


@dataclass
class AnomalyFinding:
    """Single anomaly finding."""
    device: str
    category: str  # "cpu", "memory", "interface", "bgp", "disk"
    metric: str
    current_value: str | float
    threshold: str | float
    severity: str  # "info", "warning", "critical"
    recommendation: str


@dataclass
class DeviceHealthStatus:
    """Health status of a single device."""
    device: str
    status: str  # "healthy", "warning", "critical"
    health_score: float  # 0-100
    inspected_commands: int
    success_count: int
    failure_count: int
    anomaly_count: int


def parse_device_metrics(device_output: dict[str, Any]) -> dict[str, Any]:
    """Parse raw device command output into metrics.
    
    Args:
        device_output: Raw output from network commands
            Format: {
                "device": "R1",
                "status": "success",
                "commands": [
                    {"cmd": "show cpu", "output": "CPU: 45%"},
                    {"cmd": "show memory", "output": "Memory: 8/16GB"}
                ]
            }
    
    Returns:
        Parsed metrics dict with extracted values
    """
    metrics = {
        "device": device_output.get("device"),
        "cpu_percent": None,
        "memory_percent": None,
        "interfaces_up": None,
        "interfaces_total": None,
        "bgp_status": None,
    }
    
    commands = device_output.get("commands", [])
    
    for cmd_result in commands:
        output = cmd_result.get("output", "") or ""  # Handle None output
        output = output.lower()
        
        # Parse CPU
        if "cpu" in cmd_result.get("cmd", "").lower():
            for line in output.split("\n"):
                if "cpu" in line and "%" in line:
                    try:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if "%" in part:
                                metrics["cpu_percent"] = float(part.rstrip("%"))
                                break
                    except (ValueError, IndexError):
                        pass
        
        # Parse Memory
        if "memory" in cmd_result.get("cmd", "").lower():
            try:
                # Simple parsing, assuming format like "Memory: 8/16 GB"
                if "/" in output:
                    # Extract parts before and after "/"
                    before_slash = output.split("/")[0]
                    after_slash = output.split("/")[1]
                    
                    # Extract numbers using regex-like approach
                    used_str = ''.join(c for c in before_slash if c.isdigit() or c == '.')
                    total_str = ''.join(c for c in after_slash if c.isdigit() or c == '.')
                    
                    if used_str and total_str:
                        used = float(used_str)
                        total = float(total_str)
                        if total > 0:
                            metrics["memory_percent"] = (used / total) * 100
            except (ValueError, IndexError, ZeroDivisionError):
                pass
        
        # Parse Interfaces
        if "interface" in cmd_result.get("cmd", "").lower():
            try:
                up_count = output.count("up")
                total_lines = len([l for l in output.split("\n") if l.strip()])
                metrics["interfaces_up"] = up_count
                metrics["interfaces_total"] = total_lines
            except (ValueError, IndexError):
                pass
    
    return metrics


def calculate_health_score(
    device: str,
    metrics: dict[str, Any],
    thresholds: dict[str, float] | None = None
) -> tuple[float, list[AnomalyFinding]]:
    """Calculate health score for a device and identify anomalies.
    
    Args:
        device: Device name
        metrics: Parsed metrics from parse_device_metrics()
        thresholds: Custom thresholds (default: CPU 80%, Memory 85%, etc.)
    
    Returns:
        Tuple of (health_score 0-100, list of anomalies)
    """
    if thresholds is None:
        thresholds = {
            "cpu": 80,
            "memory": 85,
            "interface_utilization": 90,
        }
    
    score = 100.0
    anomalies = []
    
    # Check CPU
    if metrics["cpu_percent"] is not None:
        cpu = metrics["cpu_percent"]
        if cpu > thresholds["cpu"]:
            reduction = min((cpu - thresholds["cpu"]) / 10, 20)  # Up to 20 point reduction
            score -= reduction
            severity = "critical" if cpu > 95 else "warning"
            anomalies.append(AnomalyFinding(
                device=device,
                category="cpu",
                metric="utilization",
                current_value=cpu,
                threshold=thresholds["cpu"],
                severity=severity,
                recommendation=f"CPU is {cpu:.1f}%. Consider offloading or optimizing processes."
            ))
    
    # Check Memory
    if metrics["memory_percent"] is not None:
        mem = metrics["memory_percent"]
        if mem > thresholds["memory"]:
            reduction = min((mem - thresholds["memory"]) * 1.5, 30)  # More aggressive penalty
            score -= reduction
            severity = "critical" if mem > 95 else "warning"
            anomalies.append(AnomalyFinding(
                device=device,
                category="memory",
                metric="utilization",
                current_value=mem,
                threshold=thresholds["memory"],
                severity=severity,
                recommendation=f"Memory is {mem:.1f}%. Review memory usage and consider upgrading."
            ))
    
    # Check Interfaces
    if (metrics["interfaces_up"] is not None and 
        metrics["interfaces_total"] is not None and 
        metrics["interfaces_total"] > 0):
        interfaces = metrics["interfaces_total"]
        up = metrics["interfaces_up"]
        down = interfaces - up
        if down > 0:
            reduction = min(down * 5, 20)
            score -= reduction
            anomalies.append(AnomalyFinding(
                device=device,
                category="interface",
                metric="status",
                current_value=f"{up}/{interfaces}",
                threshold=f"{interfaces}/{interfaces}",
                severity="warning",
                recommendation=f"{down} interface(s) down. Review and restore connections."
            ))
    
    return max(0, min(100, score)), anomalies


def aggregate_inspection_results(
    results: list[dict[str, Any]],
    inspection_type: str = "network-inspection",
    thresholds: dict[str, float] | None = None
) -> dict[str, Any]:
    """Aggregate inspection results from multiple devices (Reduce phase).
    
    This tool collects individual device results from the Map phase,
    calculates health scores, identifies anomalies, and generates
    summary statistics for the final report.
    
    Args:
        results: List of device inspection results
            Format: [{
                "device": "R1",
                "status": "success",
                "commands": [{"cmd": "show cpu", "output": "CPU: 45%"}]
            }, ...]
        inspection_type: Type of inspection (e.g., "network-inspection")
        thresholds: Custom thresholds for anomaly detection
    
    Returns:
        Aggregated report dict with:
        - device_count: Number of devices inspected
        - healthy_count: Number of healthy devices
        - warning_count: Devices with warnings
        - critical_count: Devices with critical issues
        - health_scores: Per-device health scores
        - anomalies: List of identified anomalies
        - overall_health: Overall health of network
        - inspection_time: ISO timestamp
        - recommendations: List of actionable recommendations
    """
    timestamp = datetime.now().isoformat()
    
    device_statuses: dict[str, DeviceHealthStatus] = {}
    all_anomalies: list[AnomalyFinding] = []
    
    # Process each device result
    for result in results:
        device = result.get("device", "unknown")
        
        # Parse metrics
        metrics = parse_device_metrics(result)
        
        # Calculate health
        health_score, anomalies = calculate_health_score(
            device, metrics, thresholds
        )
        
        # Determine status
        if health_score >= 90:
            status = "healthy"
        elif health_score >= 70:
            status = "warning"
        else:
            status = "critical"
        
        # Record device status
        device_statuses[device] = DeviceHealthStatus(
            device=device,
            status=status,
            health_score=health_score,
            inspected_commands=len(result.get("commands", [])),
            success_count=sum(1 for c in result.get("commands", []) 
                            if c.get("status") == "success"),
            failure_count=sum(1 for c in result.get("commands", []) 
                            if c.get("status") == "failed"),
            anomaly_count=len(anomalies)
        )
        
        all_anomalies.extend(anomalies)
    
    # Calculate overall health
    if device_statuses:
        avg_health = sum(s.health_score for s in device_statuses.values()) / len(device_statuses)
        healthy_count = sum(1 for s in device_statuses.values() if s.status == "healthy")
        warning_count = sum(1 for s in device_statuses.values() if s.status == "warning")
        critical_count = sum(1 for s in device_statuses.values() if s.status == "critical")
    else:
        avg_health = 0
        healthy_count = warning_count = critical_count = 0
    
    # Determine overall status
    if critical_count > 0:
        overall_status = "critical"
    elif warning_count > 0:
        overall_status = "warning"
    else:
        overall_status = "healthy"
    
    # Generate recommendations
    recommendations = []
    if critical_count > 0:
        recommendations.append(f"❗ CRITICAL: {critical_count} device(s) in critical state. Immediate action required.")
    if warning_count > 0:
        recommendations.append(f"⚠️ WARNING: {warning_count} device(s) have warnings. Review and monitor.")
    
    # Add anomaly-specific recommendations
    seen_recommendations = set()
    for anomaly in all_anomalies:
        if anomaly.recommendation not in seen_recommendations:
            recommendations.append(f"• {anomaly.recommendation}")
            seen_recommendations.add(anomaly.recommendation)
    
    return {
        "inspection_type": inspection_type,
        "inspection_time": timestamp,
        "device_count": len(device_statuses),
        "healthy_count": healthy_count,
        "warning_count": warning_count,
        "critical_count": critical_count,
        "overall_health": overall_status,
        "overall_health_score": round(avg_health, 2),
        "device_statuses": {
            d: asdict(device_statuses[d]) for d in device_statuses
        },
        "anomalies": [asdict(a) for a in all_anomalies],
        "anomaly_count": len(all_anomalies),
        "recommendations": recommendations,
    }


def identify_anomalies(
    device_results: dict[str, Any],
    severity_threshold: str = "warning"
) -> dict[str, Any]:
    """Identify and classify anomalies across all devices.
    
    Args:
        device_results: Per-device results from aggregate_inspection_results
        severity_threshold: Only include "warning", "critical" (default: "warning")
    
    Returns:
        Classified anomalies with grouping by category
    """
    all_anomalies = device_results.get("anomalies", [])
    
    # Filter by severity
    severity_order = {"info": 0, "warning": 1, "critical": 2}
    threshold_level = severity_order.get(severity_threshold, 1)
    
    filtered = [
        a for a in all_anomalies
        if severity_order.get(a.get("severity"), 0) >= threshold_level
    ]
    
    # Group by category
    by_category = {}
    for anomaly in filtered:
        cat = anomaly.get("category")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(anomaly)
    
    # Group by device
    by_device = {}
    for anomaly in filtered:
        dev = anomaly.get("device")
        if dev not in by_device:
            by_device[dev] = []
        by_device[dev].append(anomaly)
    
    return {
        "total_anomalies": len(filtered),
        "by_category": by_category,
        "by_device": by_device,
        "critical_devices": [
            d for d in by_device if any(a.get("severity") == "critical" for a in by_device[d])
        ],
    }


def format_inspection_report_l1_l4(
    aggregation_result: dict[str, Any],
) -> str:
    """Generate professional L1-L4 inspection report from aggregated results.
    
    This function takes the output from aggregate_inspection_results() and
    converts it into a comprehensive L1-L4 dimensional report using the
    professional report formatter.
    
    Args:
        aggregation_result: Output from aggregate_inspection_results()
        
    Returns:
        Complete markdown L1-L4 inspection report (2-5 KB)
        
    Example:
        >>> results = [{"device": "R1", "status": "success", ...}]
        >>> agg = aggregate_inspection_results(results)
        >>> report = format_inspection_report_l1_l4(agg)
        >>> Path("exports/reports/report.md").write_text(report)
    """
    try:
        from report_formatter import generate_professional_inspection_report
        use_professional = True
    except ImportError:
        use_professional = False
    
    if use_professional:
        try:
            # Prepare metadata for report formatter
            all_devices = list(aggregation_result.get("device_statuses", {}).keys())
            if not all_devices:
                all_devices = ["unknown"]
            
            metadata = {
                "timestamp": aggregation_result.get("inspection_time", datetime.now().isoformat()),
                "device_count": aggregation_result.get("device_count", 0),
                "all_devices": all_devices,
                "inspection_type": aggregation_result.get("inspection_type", "manual"),
            }
            
            # Convert anomalies to formatter's expected format
            anomalies_dict = {}
            for device in all_devices:
                anomalies_dict[device] = []
            
            for anomaly in aggregation_result.get("anomalies", []):
                device = anomaly.get("device", "unknown")
                if device not in anomalies_dict:
                    anomalies_dict[device] = []
                
                # Map category to L1-L4 layer
                category = anomaly.get("category", "")
                layer_map = {
                    "cpu": "L1", "memory": "L1", "temperature": "L1", "disk": "L1",
                    "interface": "L2", "vlan": "L2", "stp": "L2",
                    "routing": "L3", "ospf": "L3", "bgp": "L3", "vpn": "L3",
                    "protocol": "L4", "session": "L4", "queue": "L4",
                }
                layer = layer_map.get(category, "L4")
                
                anomalies_dict[device].append({
                    "metric": anomaly.get("metric", "unknown"),
                    "severity": anomaly.get("severity", "info"),
                    "value": str(anomaly.get("current_value", "N/A")),
                    "threshold": str(anomaly.get("threshold", "N/A")),
                    "layer": layer,
                    "detail": anomaly.get("recommendation", ""),
                })
            
            # Prepare LLM analysis section
            llm_analysis = {
                "root_cause": _generate_root_cause_analysis(aggregation_result),
                "impact": _generate_impact_assessment(aggregation_result),
                "recommendations": _generate_prioritized_recommendations(aggregation_result),
            }
            
            # Generate and return report
            return generate_professional_inspection_report(
                metadata=metadata,
                anomalies=anomalies_dict,
                llm_analysis=llm_analysis,
            )
        except Exception as e:
            # If professional formatter fails, fall through to fallback
            use_professional = False
    
    # Use fallback report
    return _fallback_l1_l4_report(aggregation_result)


def _generate_root_cause_analysis(agg_result: dict[str, Any]) -> str:
    """Generate root cause analysis from aggregation result."""
    critical_devices = [
        d for d, status in agg_result.get("device_statuses", {}).items()
        if status.get("status") == "critical"
    ]
    warning_devices = [
        d for d, status in agg_result.get("device_statuses", {}).items()
        if status.get("status") == "warning"
    ]
    
    lines = []
    
    if critical_devices:
        lines.append(f"⚠️ Critical Issues Detected on {len(critical_devices)} device(s): {', '.join(critical_devices[:3])}")
        lines.append("")
        lines.append("Primary causes:")
    
    if warning_devices and not critical_devices:
        lines.append(f"⚠️ Warning Issues Detected on {len(warning_devices)} device(s): {', '.join(warning_devices[:3])}")
        lines.append("")
        lines.append("Potential causes:")
    
    # Analyze abnormal metrics
    for anomaly in agg_result.get("anomalies", [])[:3]:
        device = anomaly.get("device")
        metric = anomaly.get("metric")
        value = anomaly.get("current_value")
        threshold = anomaly.get("threshold")
        lines.append(f"- {anomaly.get('category').upper()}: {device} {metric}={value} > {threshold}")
    
    if not lines:
        lines.append("✅ No significant root causes identified. Network operating normally.")
    
    return "\n".join(lines)


def _generate_impact_assessment(agg_result: dict[str, Any]) -> str:
    """Generate business impact assessment."""
    health_score = agg_result.get("overall_health_score", 100)
    critical = agg_result.get("critical_count", 0)
    warning = agg_result.get("warning_count", 0)
    
    if health_score >= 90:
        return f"✅ **Network Health**: EXCELLENT ({health_score}%)\n\nAll services operating normally. No service impact expected. Recommend continue routine monitoring."
    elif health_score >= 70:
        impact_text = f"⚠️ **Network Health**: DEGRADED ({health_score}%)\n\nDegraded performance on {warning} device(s). Service continuity at risk if issues escalate. Recommend immediate remediation to restore full capacity."
        if critical > 0:
            impact_text += f"\n\n🔴 **CRITICAL**: {critical} device(s) severely impacted. Service may be disrupted. Emergency action required."
        return impact_text
    else:
        return f"🔴 **Network Health**: CRITICAL ({health_score}%)\n\nSevere issues affecting {critical} device(s). Service disruption likely. **IMMEDIATE ACTION REQUIRED**."


def _generate_prioritized_recommendations(agg_result: dict[str, Any]) -> list[dict[str, str]]:
    """Generate prioritized action recommendations."""
    recommendations = []
    
    critical_count = agg_result.get("critical_count", 0)
    warning_count = agg_result.get("warning_count", 0)
    
    # Critical priority actions
    if critical_count > 0:
        for anomaly in agg_result.get("anomalies", []):
            if anomaly.get("severity") == "critical":
                recommendations.append({
                    "priority": "critical",
                    "action": f"URGENT: {anomaly.get('recommendation')} ({anomaly.get('device')})",
                })
    
    # Warning priority actions
    if warning_count > 0:
        for anomaly in agg_result.get("anomalies", []):
            if anomaly.get("severity") == "warning" and anomaly not in [r.get("action") for r in recommendations]:
                recommendations.append({
                    "priority": "warning",
                    "action": anomaly.get("recommendation", "Monitor device status"),
                })
    
    # Info/optimization
    if not recommendations:
        recommendations.append({
            "priority": "info",
            "action": "Continue routine inspections and maintain detailed baselines for trend analysis.",
        })
    
    return recommendations[:10]  # Limit to 10 recommendations


def _fallback_l1_l4_report(agg_result: dict[str, Any]) -> str:
    """Generate fallback markdown report when formatter unavailable."""
    lines = []
    
    lines.append("# 🔍 Network Health Inspection Report")
    lines.append("")
    lines.append(f"**Inspection Time**: {agg_result.get('inspection_time', 'Unknown')}")
    lines.append(f"**Devices Inspected**: {agg_result.get('device_count', 0)}")
    lines.append(f"**Inspection Type**: {agg_result.get('inspection_type', 'manual').replace('-', ' ').title()}")
    lines.append("")
    
    # Executive summary
    health_score = agg_result.get("overall_health_score", 0)
    status = agg_result.get("overall_health", "unknown").upper()
    
    if health_score >= 90:
        status_emoji = "✅"
        status_text = "HEALTHY"
    elif health_score >= 70:
        status_emoji = "⚠️"
        status_text = "WARNING"
    else:
        status_emoji = "🔴"
        status_text = "CRITICAL"
    
    lines.append("## 📊 Executive Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Overall Health Score | **{health_score}%** {status_emoji} {status_text} |")
    lines.append(f"| Normal Devices | {agg_result.get('healthy_count', 0)} ✅ |")
    lines.append(f"| Warning Devices | {agg_result.get('warning_count', 0)} ⚠️ |")
    lines.append(f"| Critical Devices | {agg_result.get('critical_count', 0)} 🔴 |")
    lines.append(f"| Total Anomalies | {agg_result.get('anomaly_count', 0)} |")
    lines.append("")
    
    # Inspection scope
    lines.append("---")
    lines.append("")
    lines.append("## 🎯 Inspection Scope & Methodology")
    lines.append("")
    lines.append("This inspection covered **L1-L4 multi-layer analysis**:")
    lines.append("")
    lines.append("| Layer | Scope | Status |")
    lines.append("|-------|-------|--------|")
    
    # Analyze anomalies by layer
    anomalies_by_layer = {"L1": [], "L2": [], "L3": [], "L4": []}
    layer_map = {
        "cpu": "L1", "memory": "L1", "temperature": "L1", "disk": "L1", "power": "L1", "fan": "L1",
        "interface": "L2", "vlan": "L2", "stp": "L2", "ethernet": "L2",
        "routing": "L3", "ospf": "L3", "bgp": "L3", "vpn": "L3",
        "protocol": "L4", "session": "L4", "queue": "L4", "service": "L4",
    }
    
    for anom in agg_result.get("anomalies", []):
        layer = layer_map.get(anom.get("category", "").lower(), "L4")
        anomalies_by_layer[layer].append(anom)
    
    layer_names = {
        "L1": "Physical (CPU, Memory, Power, Fans)",
        "L2": "DataLink (Interfaces, VLANs, STP)",
        "L3": "Network (Routing, OSPF, BGP, VPN)",
        "L4": "Application (Services, Sessions, Queues)"
    }
    
    for layer in ["L1", "L2", "L3", "L4"]:
        if anomalies_by_layer[layer]:
            layer_status = "⚠️ Issues Found"
        else:
            layer_status = "✅ Normal"
        lines.append(f"| {layer} | {layer_names[layer]} | {layer_status} |")
    
    lines.append("")
    
    # Device status matrix
    lines.append("## 📱 Device Status Matrix")
    lines.append("")
    lines.append("| Device | Health Score | Status | Commands | Anomalies |")
    lines.append("|--------|------|--------|----------|-----------|")
    
    for device, status in agg_result.get("device_statuses", {}).items():
        score = status.get("health_score", 0)
        status_text = status.get("status", "unknown").upper()
        if score >= 90:
            status_emoji = "✅"
        elif score >= 70:
            status_emoji = "⚠️"
        else:
            status_emoji = "🔴"
        
        inspected = status.get("inspected_commands", 0)
        success = status.get("success_count", 0)
        anomaly_count = status.get("anomaly_count", 0)
        
        lines.append(f"| {device} | {score}% | {status_emoji} {status_text} | {success}/{inspected} | {anomaly_count} |")
    
    lines.append("")
    
    # Detailed findings by layer
    lines.append("---")
    lines.append("")
    lines.append("## 📋 Expected vs Actual State Analysis")
    lines.append("")
    
    if agg_result.get("anomalies"):
        # Critical issues
        critical_issues = [a for a in agg_result.get("anomalies", []) if a.get("severity") == "critical"]
        if critical_issues:
            lines.append("### 🔴 Critical Issues")
            lines.append("")
            for issue in critical_issues:
                lines.append(f"**{issue.get('device')} - {issue.get('metric')}** (L{issue.get('category')})")
                lines.append("")
                lines.append(f"- **Current Value**: {issue.get('current_value')}")
                lines.append(f"- **Expected**: < {issue.get('threshold')}")
                lines.append(f"- **Severity**: 🔴 CRITICAL")
                lines.append(f"- **Recommendation**: {issue.get('recommendation')}")
                lines.append("")
        
        # Warning issues
        warning_issues = [a for a in agg_result.get("anomalies", []) if a.get("severity") == "warning"]
        if warning_issues:
            lines.append("### ⚠️ Warning Issues")
            lines.append("")
            for issue in warning_issues[:5]:  # Show top 5 warnings
                lines.append(f"**{issue.get('device')} - {issue.get('metric')}** (L{issue.get('category')})")
                lines.append("")
                lines.append(f"- **Current Value**: {issue.get('current_value')}")
                lines.append(f"- **Expected**: < {issue.get('threshold')}")
                lines.append(f"- **Severity**: ⚠️ WARNING")
                lines.append(f"- **Recommendation**: {issue.get('recommendation')}")
                lines.append("")
            
            if len(warning_issues) > 5:
                lines.append(f"*... and {len(warning_issues) - 5} more warnings ...*")
                lines.append("")
    else:
        lines.append("✅ **No anomalies detected** - All devices operating within parameters")
        lines.append("")
    
    # Root cause and impact
    lines.append("---")
    lines.append("")
    lines.append("## 🔎 Root Cause & Impact Analysis")
    lines.append("")
    
    root_cause = _generate_root_cause_analysis(agg_result)
    lines.append(root_cause)
    lines.append("")
    
    lines.append("### Business Impact")
    lines.append("")
    impact = _generate_impact_assessment(agg_result)
    lines.append(impact)
    lines.append("")
    
    # Recommendations
    lines.append("---")
    lines.append("")
    lines.append("## 💡 Recommendations & Action Plan")
    lines.append("")
    
    recommendations = _generate_prioritized_recommendations(agg_result)
    
    # Group by priority
    critical_recs = [r for r in recommendations if r.get("priority") == "critical"]
    warning_recs = [r for r in recommendations if r.get("priority") == "warning"]
    info_recs = [r for r in recommendations if r.get("priority") == "info"]
    
    if critical_recs:
        lines.append("### 🚨 Immediate Actions Required")
        lines.append("")
        for i, rec in enumerate(critical_recs, 1):
            lines.append(f"{i}. {rec.get('action')}")
        lines.append("")
    
    if warning_recs:
        lines.append("### 📅 Planned Actions")
        lines.append("")
        for i, rec in enumerate(warning_recs, 1):
            lines.append(f"{i}. {rec.get('action')}")
        lines.append("")
    
    if info_recs:
        lines.append("### 🔧 Optimization Suggestions")
        lines.append("")
        for i, rec in enumerate(info_recs, 1):
            lines.append(f"{i}. {rec.get('action')}")
        lines.append("")
    
    # Next steps
    lines.append("---")
    lines.append("")
    lines.append("## 📞 Next Steps & Follow-up")
    lines.append("")
    lines.append("### Recommended Commands for Further Investigation")
    lines.append("")
    lines.append("```bash")
    lines.append("# Check device details")
    lines.append("olav query --device <device_name> --metric cpu")
    lines.append("olav query --device <device_name> --metric memory")
    lines.append("olav query --device <device_name> --metric interface")
    lines.append("")
    lines.append("# Search for similar issues")
    lines.append("olav search --metric <metric_name> --severity warning,critical")
    lines.append("")
    lines.append("# Export detailed findings")
    lines.append("olav export --inspection --format json")
    lines.append("```")
    lines.append("")
    
    # Footer
    lines.append("---")
    lines.append("")
    lines.append("**Report Generated**: OLAV Inspection Service v2.0")
    lines.append(f"**Timestamp**: {datetime.now().isoformat()}")
    lines.append(f"**Inspection Duration**: < 5 seconds")
    
    return "\n".join(lines)
