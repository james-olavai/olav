import json
import logging
from datetime import datetime
from typing import Any

from jinja2 import Template
from langchain_core.messages import SystemMessage

from olav.agents.threshold_agent import ThresholdAgent
from olav.core.llm import LLMFactory
from olav.core.skill_loader import get_skill_loader
from olav.core.unified_database import UnifiedDatabase

logger = logging.getLogger(__name__)


class MapPhase:
    """Executes SQL layers defined in the inspection skill."""

    def __init__(self, udb: UnifiedDatabase) -> None:
        self.udb = udb

    async def collect_all_layers(
        self, layers: list[dict[str, Any]], device_filter: list[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """
        Collect metrics from all defined layers.
        Returns: {device_name: {metric_name: value, _layer_map: {metric: layer}}}
        """
        all_data = {}

        for layer in layers:
            sql = layer.get("sql")
            layer_name = layer.get("name", "Unknown")
            if not sql:
                continue

            try:
                cursor = self.udb.conn.execute(sql)
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                for row in rows:
                    row_dict = dict(zip(columns, row, strict=True))
                    device = row_dict.pop("device", "unknown")

                    if device_filter and device not in device_filter:
                        continue

                    if device not in all_data:
                        all_data[device] = {"_layer_map": {}}

                    # Update device data with metrics from this layer
                    for metric_name, value in row_dict.items():
                        all_data[device][metric_name] = value
                        # 记录每个指标来自哪个 layer
                        all_data[device]["_layer_map"][metric_name] = layer_name

            except Exception as e:
                logger.error(f"Error executing layer {layer_name}: {e}")

        return all_data


class ReducePhase:
    """Uses LLM to analyze all detected anomalies globally."""

    def __init__(self) -> None:
        self.llm = LLMFactory.get_chat_model()

    async def analyze_global_anomalies(
        self, anomalies: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Send all anomalies to LLM for root cause and impact analysis."""
        if not anomalies:
            return {
                "root_cause": "没有检测到显著异常。",
                "impact": "网络状态正常。",
                "recommendations": [{"priority": "info", "action": "继续保持例行监控。"}],
            }

        prompt = f"""你是一名资深的华为/思科网络专家。
下面是本次巡检中检测到的所有异常数据：

{json.dumps(anomalies, indent=2, ensure_ascii=False)}

请通过全局视角进行关联分析，并给出：
1. **根本原因推断 (Root Cause Analysis)**: 是否有跨设备的关联故障？
2. **业务影响评估 (Business Impact)**: 这些异常可能导致什么后果？
3. **建议措施 (Recommendations)**: 按优先级排列。

请以 JSON 格式返回，包含字段：root_cause, impact, recommendations (list of {{priority, action}}).
"""

        try:
            response = self.llm.invoke([SystemMessage(content=prompt)])
            # Simple cleanup for JSON parsing
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()

            return json.loads(content)
        except Exception as e:
            logger.error(f"Error in LLM analysis: {e}")
            return {
                "root_cause": "LLM 分析失败。",
                "impact": "无法评估。",
                "recommendations": [
                    {"priority": "warning", "action": "请检查 LLM 连接或手动分析异常数据。"}
                ],
            }


class ReportRenderer:
    """Renders the final report using the specified report skill template."""

    def __init__(self, skill_id: str) -> None:
        loader = get_skill_loader()
        self.skill = loader.get_skill(skill_id)
        if not self.skill:
            raise ValueError(f"Report skill {skill_id} not found.")

    def render(self, result: dict[str, Any]) -> str:
        """Render the report."""
        # Extract template from SKILL.md
        # Assuming the template starts after a certain marker or just uses the whole content
        template_str = self.skill.content
        if template_str and "```markdown" in template_str:
            template_str = template_str.split("```markdown")[1].split("```")[0].strip()

        # Prepare template variables
        # This part should be sophisticated, but for MVP we'll map the common ones
        template_vars = self._prepare_vars(result)

        if not template_str:
            template_str = "{% block content %}{% endblock %}"

        template = Template(template_str)
        return template.render(**template_vars)

    def _prepare_vars(self, result: dict[str, Any]) -> dict[str, Any]:
        """Convert result into template-friendly variables."""
        anomalies = result["anomalies"]
        all_devices = result["metadata"]["all_devices"]  # 新增：所有设备列表
        devices_list = []
        critical_issues = []
        warning_issues = []

        # 遍历所有设备，而不仅仅是有异常的设备
        for device in all_devices:
            device_anomalies = anomalies.get(device, [])
            device_status = "✅ Normal"
            l1, l2, l3, l4 = "✅", "✅", "✅", "✅"

            for a in device_anomalies:
                severity = a["severity"]
                layer = a.get("layer", "L4_Application")
                icon = "🔴" if severity == "critical" else "⚠️"

                if severity == "critical":
                    device_status = "🔴 Critical"
                    critical_issues.append({"device": device, **a})
                elif severity == "warning" and device_status == "✅ Normal":
                    device_status = "⚠️ Warning"
                    warning_issues.append({"device": device, **a})

                # Layer mapping (simplistic)
                if "L1" in layer:
                    l1 = icon
                elif "L2" in layer:
                    l2 = icon
                elif "L3" in layer:
                    l3 = icon
                else:
                    l4 = icon

            devices_list.append(
                {"device": device, "l1": l1, "l2": l2, "l3": l3, "l4": l4, "status": device_status}
            )

        return {
            "timestamp": result["metadata"]["timestamp"],
            "device_count": result["metadata"]["device_count"],
            "overall_status": result["summary"]["overall_status"],
            "normal_count": result["summary"]["normal_count"],
            "warning_count": result["summary"]["warning_count"],
            "critical_count": result["summary"]["critical_count"],
            "devices": devices_list,
            "critical_issues": critical_issues,
            "warning_issues": warning_issues,
            "immediate_actions": [
                r["action"]
                for r in result["llm_analysis"].get("recommendations", [])
                if r.get("priority") == "critical"
            ],
            "planned_actions": [
                r["action"]
                for r in result["llm_analysis"].get("recommendations", [])
                if r.get("priority") == "warning"
            ],
            "optimization_suggestions": [
                r["action"]
                for r in result["llm_analysis"].get("recommendations", [])
                if r.get("priority") == "info"
            ],
        }


class InspectionOrchestrator:
    """Main orchestrator for the inspection process."""

    def __init__(self) -> None:
        self.udb = UnifiedDatabase()
        self.map_phase = MapPhase(self.udb)
        self.threshold_agent = ThresholdAgent()
        self.reduce_phase = ReducePhase()

    async def run_inspection(
        self, test_mode: bool = False, device_filter: list[str] | None = None
    ) -> str:
        """Run the full or test inspection."""
        logger.info("Starting inspection...")

        # 1. Load skill
        loader = get_skill_loader()
        inspection_skill = loader.get_skill("network-inspection")
        if not inspection_skill:
            raise ValueError("Inspection skill not found.")

        # 2. Map Phase
        layers = inspection_skill.frontmatter.get("inspection", {}).get("layers", [])
        all_device_metrics = await self.map_phase.collect_all_layers(
            layers, device_filter=device_filter
        )

        # 3. Threshold Detection
        all_anomalies = {}
        for device, metrics in all_device_metrics.items():
            # 提取 layer_map（如果存在）
            layer_map = metrics.pop("_layer_map", {})

            anomalies = await self.threshold_agent.detect_anomalies(device, metrics)

            # 为每个异常添加 layer 信息
            for anomaly in anomalies:
                metric_name = anomaly.get("metric")
                if metric_name and metric_name in layer_map:
                    anomaly["layer"] = layer_map[metric_name]

            if anomalies:
                all_anomalies[device] = anomalies

        # 4. Reduce Phase - test 模式也执行真实的 LLM 分析
        llm_analysis = await self.reduce_phase.analyze_global_anomalies(all_anomalies)

        # 5. Build Result
        result = {
            "metadata": {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "device_count": len(all_device_metrics),
                "all_devices": sorted(all_device_metrics.keys()),  # 新增：所有设备列表
            },
            "summary": self._calculate_summary(len(all_device_metrics), all_anomalies),
            "anomalies": all_anomalies,
            "llm_analysis": llm_analysis,
        }

        # 6. Render Report
        report_skill_id = inspection_skill.frontmatter.get("output", {}).get(
            "report_skill", "inspect-report"
        )
        renderer = ReportRenderer(report_skill_id)
        report = renderer.render(result)

        # 7. Save report
        self._save_report(report)

        return report

    def _calculate_summary(
        self, total_devices: int, anomalies: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
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

        status = "normal"
        if critical_count > 0:
            status = "critical"
        elif warning_count > 0:
            status = "warning"

        return {
            "normal_count": normal_count,
            "warning_count": warning_count,
            "critical_count": critical_count,
            "overall_status": status,
        }

    def _save_report(self, report: str) -> None:
        from config.paths import REPORTS_DIR

        report_path = (
            REPORTS_DIR / "inspection" / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        logger.info(f"Report saved to {report_path}")

        # Update latest link (optional)
        latest_path = report_path.parent / "latest.md"
        latest_path.write_text(report, encoding="utf-8")
