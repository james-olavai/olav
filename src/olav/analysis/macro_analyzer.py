"""Macro-level network analyzer.

Performs comprehensive network analysis using unified database queries:
- Health scoring across L1-L4 layers
- Anomaly detection
- Trend analysis
- Problem correlation with knowledge base
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from olav.analysis.health_score import (
    calculate_layer_score,
    calculate_overall_score,
    format_score_report,
)
from olav.core.unified_database import UnifiedDatabase


class MacroAnalyzer:
    """Macro-level network analyzer using unified database.

    Provides comprehensive analysis capabilities:
    - Multi-layer health scoring
    - Anomaly detection
    - Historical trend analysis
    - Knowledge correlation

    Example:
        >>> analyzer = MacroAnalyzer()
        >>> report = analyzer.generate_full_analysis("2026-01-14")
        >>> print(report["sections"]["health_summary"])
        >>> analyzer.close()
    """

    def __init__(self):
        """Initialize analyzer with unified database connection."""
        self.db = UnifiedDatabase()

    def generate_full_analysis(
        self, snapshot_date: str | None = None
    ) -> dict[str, Any]:
        """Generate comprehensive network analysis report.

        Args:
            snapshot_date: Snapshot date (YYYY-MM-DD), defaults to latest

        Returns:
            Dictionary with analysis sections
        """
        if snapshot_date is None:
            snapshot_date = self._get_latest_snapshot_date()

        report = {
            "generated_at": datetime.now().isoformat(),
            "snapshot_date": snapshot_date,
            "sections": {},
        }

        # 1. Network health scoring
        report["sections"]["health_summary"] = self._analyze_health(
            snapshot_date
        )

        # 2. Anomaly detection
        report["sections"]["anomalies"] = self._detect_anomalies(snapshot_date)

        # 3. Device-level analysis
        report["sections"]["device_health"] = self._analyze_devices(
            snapshot_date
        )

        # 4. Topology correlation
        report["sections"]["topology_health"] = (
            self._correlate_topology_health(snapshot_date)
        )

        return report

    def _get_latest_snapshot_date(self) -> str:
        """Get the most recent snapshot date from database."""
        result = self.db.query(
            "SELECT MAX(snapshot_date) FROM snapshot.arp_table"
        )
        if result and result[0][0]:
            return str(result[0][0])
        return datetime.now().strftime("%Y-%m-%d")

    def _analyze_health(self, snapshot_date: str) -> dict[str, Any]:
        """Analyze network health across all layers.

        Args:
            snapshot_date: Snapshot date

        Returns:
            Dictionary with health scores and metrics
        """
        layer_scores = {}

        # L1: Physical Layer (interfaces)
        l1_metrics = self._get_l1_metrics(snapshot_date)
        if l1_metrics:
            l1_score = calculate_layer_score("L1", l1_metrics)
            layer_scores["L1"] = l1_score["score"]

        # L2: Data Link Layer (VLANs, STP)
        l2_metrics = self._get_l2_metrics(snapshot_date)
        if l2_metrics:
            l2_score = calculate_layer_score("L2", l2_metrics)
            layer_scores["L2"] = l2_score["score"]

        # L3: Network Layer (Routes, OSPF)
        l3_metrics = self._get_l3_metrics(snapshot_date)
        if l3_metrics:
            l3_score = calculate_layer_score("L3", l3_metrics)
            layer_scores["L3"] = l3_score["score"]

        # L4: Transport Layer (BGP)
        l4_metrics = self._get_l4_metrics(snapshot_date)
        if l4_metrics:
            l4_score = calculate_layer_score("L4", l4_metrics)
            layer_scores["L4"] = l4_score["score"]

        # Calculate overall score
        overall = calculate_overall_score(layer_scores)

        return {
            "overall_score": overall["score"],
            "overall_status": overall["status"],
            "layer_scores": layer_scores,
            "summary": self._format_health_summary(overall, layer_scores),
        }

    def _get_l1_metrics(self, snapshot_date: str) -> dict[str, int]:
        """Get L1 (Physical Layer) metrics from interfaces table."""
        # Note: interfaces table not yet populated in current implementation
        # Return empty dict for now
        return {}

    def _get_l2_metrics(self, snapshot_date: str) -> dict[str, int]:
        """Get L2 (Data Link Layer) metrics from VLANs table."""
        # Note: vlans table not yet populated
        return {}

    def _get_l3_metrics(self, snapshot_date: str) -> dict[str, int]:
        """Get L3 (Network Layer) metrics from routes table."""
        result = self.db.query(
            """
            SELECT 
                COUNT(*) as total_routes,
                SUM(CASE WHEN protocol = 'C' THEN 1 ELSE 0 END) as connected,
                SUM(CASE WHEN protocol = 'S' THEN 1 ELSE 0 END) as static,
                SUM(CASE WHEN protocol = 'O' THEN 1 ELSE 0 END) as ospf
            FROM snapshot.routes
            WHERE snapshot_date = ?
        """,
            [snapshot_date],
        )

        if result and result[0]:
            total, connected, static, ospf = result[0]
            return {
                "route_active": total or 0,
                "static_route": static or 0,
            }
        return {}

    def _get_l4_metrics(self, snapshot_date: str) -> dict[str, int]:
        """Get L4 (Transport Layer) metrics from BGP table."""
        # Note: bgp_neighbors table not yet populated
        return {}

    def _detect_anomalies(self, snapshot_date: str) -> list[dict[str, Any]]:
        """Detect network anomalies.

        Args:
            snapshot_date: Snapshot date

        Returns:
            List of detected anomalies
        """
        anomalies = []

        # Check for missing expected routes
        device_count = self.db.query(
            "SELECT COUNT(*) FROM snapshot.topology_devices"
        )[0][0]

        route_count = self.db.query(
            """
            SELECT COUNT(DISTINCT device_name) 
            FROM snapshot.routes 
            WHERE snapshot_date = ?
        """,
            [snapshot_date],
        )[0][0]

        if route_count < device_count:
            anomalies.append(
                {
                    "type": "missing_routes",
                    "severity": "warning",
                    "description": f"Only {route_count}/{device_count} devices have route data",
                    "devices_affected": device_count - route_count,
                }
            )

        # Check for ARP anomalies (too few entries)
        arp_results = self.db.query(
            """
            SELECT device_name, COUNT(*) as arp_count
            FROM snapshot.arp_table
            WHERE snapshot_date = ?
            GROUP BY device_name
            HAVING COUNT(*) < 3
        """,
            [snapshot_date],
        )

        for device, count in arp_results:
            anomalies.append(
                {
                    "type": "low_arp_count",
                    "severity": "info",
                    "description": f"Device {device} has only {count} ARP entries",
                    "device": device,
                    "count": count,
                }
            )

        return anomalies

    def _analyze_devices(self, snapshot_date: str) -> list[dict[str, Any]]:
        """Analyze health of individual devices.

        Args:
            snapshot_date: Snapshot date

        Returns:
            List of device health summaries
        """
        devices = self.db.query(
            "SELECT name FROM snapshot.topology_devices ORDER BY name"
        )

        device_health = []
        for (device_name,) in devices:
            health = self.db.get_device_health(device_name)
            health["snapshot_date"] = snapshot_date
            device_health.append(health)

        return device_health

    def _correlate_topology_health(
        self, snapshot_date: str
    ) -> list[dict[str, Any]]:
        """Correlate topology with health metrics.

        Args:
            snapshot_date: Snapshot date

        Returns:
            List of topology-health correlations
        """
        results = self.db.query(
            """
            SELECT 
                d.name,
                d.role,
                COUNT(DISTINCT l.id) as link_count,
                COUNT(DISTINCT r.network) as route_count,
                COUNT(DISTINCT a.ip_address) as arp_count
            FROM snapshot.topology_devices d
            LEFT JOIN snapshot.topology_links l ON d.name = l.local_device
            LEFT JOIN snapshot.routes r 
                ON d.name = r.device_name AND r.snapshot_date = ?
            LEFT JOIN snapshot.arp_table a 
                ON d.name = a.device_name AND a.snapshot_date = ?
            GROUP BY d.name, d.role
            ORDER BY link_count DESC, route_count DESC
        """,
            [snapshot_date, snapshot_date],
        )

        correlations = []
        for row in results:
            name, role, links, routes, arps = row
            correlations.append(
                {
                    "device": name,
                    "role": role,
                    "links": links,
                    "routes": routes,
                    "arp_entries": arps,
                    "connectivity_score": min(100, (links * 20 + routes * 5)),
                }
            )

        return correlations

    def _format_health_summary(
        self, overall: dict, layer_scores: dict
    ) -> str:
        """Format health summary as markdown.

        Args:
            overall: Overall health score
            layer_scores: Layer-specific scores

        Returns:
            Markdown formatted summary
        """
        summary = f"# Network Health Report\n\n"
        summary += f"## {overall['icon']} Overall: {overall['score']}/100 ({overall['status'].upper()})\n\n"

        if layer_scores:
            summary += "### Layer Scores\n\n"
            layer_names = {
                "L1": "Physical",
                "L2": "Data Link",
                "L3": "Network",
                "L4": "Transport",
            }
            for layer in ["L1", "L2", "L3", "L4"]:
                if layer in layer_scores:
                    score = layer_scores[layer]
                    name = layer_names[layer]
                    if score >= 80:
                        icon = "🟢"
                    elif score >= 50:
                        icon = "🟡"
                    else:
                        icon = "🔴"
                    summary += f"- {icon} **{name}**: {score}/100\n"

        return summary

    def format_report_as_markdown(self, report: dict[str, Any]) -> str:
        """Format full analysis report as markdown.

        Args:
            report: Report data from generate_full_analysis

        Returns:
            Markdown formatted report
        """
        md = f"# Network Analysis Report\n\n"
        md += f"**Generated**: {report['generated_at']}\n"
        md += f"**Snapshot Date**: {report['snapshot_date']}\n\n"

        # Health summary
        if "health_summary" in report["sections"]:
            health = report["sections"]["health_summary"]
            md += health.get("summary", "")
            md += "\n\n"

        # Anomalies
        if "anomalies" in report["sections"]:
            anomalies = report["sections"]["anomalies"]
            if anomalies:
                md += "## 🔍 Detected Anomalies\n\n"
                for anomaly in anomalies:
                    severity_icon = {
                        "critical": "🔴",
                        "warning": "🟡",
                        "info": "🔵",
                    }
                    icon = severity_icon.get(
                        anomaly["severity"], "⚪"
                    )
                    md += f"- {icon} **{anomaly['type']}**: {anomaly['description']}\n"
                md += "\n"

        # Device health
        if "device_health" in report["sections"]:
            devices = report["sections"]["device_health"]
            if devices:
                md += "## 📊 Device Health\n\n"
                md += "| Device | Platform | Role | ARP | Routes | Neighbors |\n"
                md += "|--------|----------|------|-----|--------|----------|\n"
                for dev in devices:
                    md += f"| {dev.get('device_name', 'N/A')} "
                    md += f"| {dev.get('platform', 'N/A')} "
                    md += f"| {dev.get('role', 'N/A')} "
                    md += f"| {dev.get('arp_entries', 0)} "
                    md += f"| {dev.get('routes', 0)} "
                    md += f"| {dev.get('neighbors', 0)} |\n"
                md += "\n"

        return md

    def close(self) -> None:
        """Close database connection."""
        if self.db:
            self.db.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
