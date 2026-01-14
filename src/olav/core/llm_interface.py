"""Unified Data Layer - LLM Interface for Map-Reduce Workflow.

This module provides the LLM interface for Map-Reduce operations
following the unified data layer design (docs/0.md).

Core classes:
- MapReduceLLM: LLM interface for analyze_inspect, analyze_logs, generate_report
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

# =============================================================================
# Map-Reduce LLM Interface
# =============================================================================


class MapReduceLLM:
    """LLM interface for Map-Reduce workflow.

    This class provides methods for:
    - Map phase: analyze_inspect, analyze_logs (per-device/per-command analysis)
    - Reduce phase: generate_report (global correlation and summarization)

    Attributes:
        provider: LLM provider ("anthropic" or "openai")
        model: Model name
        max_concurrent: Maximum concurrent LLM calls in Map phase
        retry_count: Number of retries on failure
        retry_delay: Delay between retries (seconds)
    """

    def __init__(
        self,
        provider: str = "anthropic",
        model: str = "claude-sonnet-4-20250514",
        max_concurrent: int = 5,
        retry_count: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """Initialize Map-Reduce LLM interface.

        Args:
            provider: LLM provider ("anthropic" or "openai")
            model: Model name
            max_concurrent: Maximum concurrent Map calls
            retry_count: Retry count on failure
            retry_delay: Delay between retries (seconds)
        """
        self.provider = provider
        self.model = model
        self.max_concurrent = max_concurrent
        self.retry_count = retry_count
        self.retry_delay = retry_delay

        # Initialize LLM client
        if provider == "anthropic":
            # Use Anthropic via OpenAI-compatible API
            self.llm = ChatOpenAI(
                model=model,
                temperature=0,
                max_tokens=2000,
                api_key=self._get_api_key("anthropic"),
                base_url="https://api.anthropic.com/v1/",
            )
        else:  # openai
            self.llm = ChatOpenAI(
                model=model,
                temperature=0,
                max_tokens=2000,
                api_key=self._get_api_key("openai"),
            )

    def _get_api_key(self, provider: str) -> str:
        """Get API key from environment.

        Args:
            provider: Provider name

        Returns:
            API key string
        """
        import os

        if provider == "anthropic":
            return os.getenv("ANTHROPIC_API_KEY", "")
        else:
            return os.getenv("OPENAI_API_KEY", "")

    # =============================================================================
    # Map Phase: analyze_inspect
    # =============================================================================

    async def analyze_inspect(
        self,
        device: str,
        layer: Literal["L1", "L2", "L3", "L4"],
        check_type: str,
        raw_output: str,
        parsed_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Map phase: Analyze single check output.

        This method performs per-command analysis using LLM to determine
        if the check result is OK, WARNING, or CRITICAL based on thresholds
        defined in the L1-L4 checking framework.

        Args:
            device: Device name
            layer: OSI layer (L1/L2/L3/L4)
            check_type: Type of check (cpu, memory, interface_errors, ospf, bgp, temperature, etc.)
            raw_output: Raw command output
            parsed_data: Optional parsed data from TextFSM

        Returns:
            Dictionary with analysis result:
            {
                "device": "R1",
                "layer": "L4",
                "check": "cpu",
                "status": "ok|warning|critical",
                "value": "62%",
                "threshold": "50%",
                "detail": "CPU利用率超过警告阈值",
                "interface": "Gi0/1"  # only for interface checks
            }

        Examples:
            >>> result = await llm.analyze_inspect("R1", "L4", "cpu", "CPU utilization: 62%")
            >>> print(result["status"])
            "warning"
        """
        # Load skill prompt
        skill_prompt = self._load_inspect_skill()

        # Build prompt with context
        prompt = f"""
{skill_prompt}

## Input Data

Device: {device}
Layer: {layer}
Check Type: {check_type}

Raw Command Output:
{raw_output[:5000]}
"""

        if parsed_data:
            prompt += f"""

Parsed Data (JSON):
{json.dumps(parsed_data, indent=2)}
"""

        prompt += """

## Task

Analyze this command output and determine if the result is OK, WARNING, or CRITICAL.
Use the threshold table above. Output ONLY a valid JSON object (no markdown, no code blocks).
"""

        # Retry logic
        for attempt in range(self.retry_count):
            try:
                messages = [SystemMessage(content=prompt)]
                response = await self.llm.ainvoke(messages)

                # Parse response
                content = response.content.strip()

                # Remove markdown code blocks if present
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                result = json.loads(content)

                # Ensure required fields
                result.setdefault("device", device)
                result.setdefault("layer", layer)
                result.setdefault("check", check_type)
                result.setdefault("status", "ok")

                return result

            except (json.JSONDecodeError, Exception) as e:
                if attempt < self.retry_count - 1:
                    import asyncio

                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    # Return error status
                    return {
                        "device": device,
                        "layer": layer,
                        "check": check_type,
                        "status": "error",
                        "error": str(e),
                    }

    def _load_inspect_skill(self) -> str:
        """Load inspect-analyzer skill prompt.

        Returns:
            Skill prompt content
        """
        skill_path = Path(".olav/skills/inspect-analyzer/SKILL.md")
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
        else:
            # Fallback: built-in prompt
            return """
## L1-L4 Checking Framework

### Threshold Table

| Check Type | WARNING | CRITICAL |
|------------|---------|----------|
| cpu | >50% | >80% |
| memory | >75% | >90% |
| temperature | >60°C | >70°C |
| interface_errors | >0 | >0.1% error rate |
| interface_drops | >0 |持续增长 |
| ospf | state != FULL | 全部邻居丢失 |
| bgp | state != ESTABLISHED | 全部会话 down |
| power | 任一 inactive | 单 PSU 模式 |
| fans | 任一 failed | - |

## Output Format

Normal (OK):
```json
{
  "device": "R1",
  "layer": "L4",
  "check": "cpu",
  "status": "ok",
  "value": "23%"
}
```

Warning:
```json
{
  "device": "R1",
  "layer": "L4",
  "check": "cpu",
  "status": "warning",
  "value": "62%",
  "threshold": "50%",
  "detail": "CPU利用率超过警告阈值"
}
```

Critical:
```json
{
  "device": "R1",
  "layer": "L4",
  "check": "cpu",
  "status": "critical",
  "value": "85%",
  "threshold": "80%",
  "detail": "CPU利用率超过临界阈值"
}
```
"""

    # =============================================================================
    # Map Phase: analyze_logs
    # =============================================================================

    async def analyze_logs(self, device: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Map phase: Analyze device log events.

        This method performs per-device log analysis using LLM to identify
        significant events that need to be reported in the daily summary.

        Args:
            device: Device name
            events: List of parsed log events (NetworkEvent dictionaries)

        Returns:
            Dictionary with analysis result:
            {
                "device": "R1",
                "status": "ok|warning",
                "event_count": 5,
                "events": [
                    {
                        "type": "ospf_neighbor_down",
                        "severity": "warning",
                        "count": 3,
                        "neighbors": ["10.1.1.2", "10.1.1.3"],
                        "first_seen": "2026-01-13T02:15:00Z",
                        "last_seen": "2026-01-13T05:30:00Z",
                        "recovered": false,
                        "detail": "3个OSPF邻居DOWN超过5分钟未恢复"
                    }
                ]
            }

        Examples:
            >>> result = await llm.analyze_logs("R1", parsed_events)
            >>> print(result["status"])
            "warning"
        """
        # Load skill prompt
        skill_prompt = self._load_log_skill()

        # Build prompt with events
        events_json = json.dumps(events[:100], indent=2)  # Limit to 100 events

        prompt = f"""
{skill_prompt}

## Input Data

Device: {device}

Events (JSON):
{events_json}
"""

        prompt += """

## Task

Analyze these log events and identify which ones need to be reported.
Use the keyword trigger table and anomaly pattern recognition rules above.
Output ONLY a valid JSON object (no markdown, no code blocks).
"""

        # Retry logic
        for attempt in range(self.retry_count):
            try:
                messages = [SystemMessage(content=prompt)]
                response = await self.llm.ainvoke(messages)

                # Parse response
                content = response.content.strip()

                # Remove markdown code blocks if present
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                result = json.loads(content)

                # Ensure required fields
                result.setdefault("device", device)
                result.setdefault("status", "ok")
                result.setdefault("event_count", 0)
                result.setdefault("events", [])

                return result

            except (json.JSONDecodeError, Exception) as e:
                if attempt < self.retry_count - 1:
                    import asyncio

                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    # Return error status
                    return {
                        "device": device,
                        "status": "error",
                        "event_count": 0,
                        "events": [],
                        "error": str(e),
                    }

    def _load_log_skill(self) -> str:
        """Load log-analyzer skill prompt.

        Returns:
            Skill prompt content
        """
        skill_path = Path(".olav/skills/log-analyzer/SKILL.md")
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
        else:
            # Fallback: built-in prompt
            return """
## Keyword Trigger Rules

### 第一阶段: 关键词匹配 (快速过滤)

| 类别 | 触发关键词 | Severity |
|------|-----------|----------|
| **错误** | `%ERROR`, `%CRITICAL`, `%ALERT` | 0-3 |
| **接口** | `UPDOWN`, `LINK-3-UPDOWN`, `changed state to down` | 3 |
| **路由** | `OSPF-5-ADJCHG`, `ADJCHG`, `neighbor down`, `went down` | 5 |
| **BGP** | `BGP-5-ADJCHANGE`, `session reset`, `connection closed` | 5 |
| **STP** | `SPANTREE-2-`, `topology change`, `root change` | 2-5 |
| **硬件** | `FAN`, `POWER`, `TEMP`, `%ENVMON` | 2-4 |
| **安全** | `SEC_LOGIN`, `AUTHEN`, `failed`, `denied` | 4-5 |
| **重启** | `RESTART`, `RELOAD`, `BOOT`, `Initializing` | 5 |

### 异常模式识别

| 模式 | 定义 | 状态 |
|------|------|------|
| **Flapping** | 同一接口 >3 次 UP/DOWN (1h内) | WARNING |
| **邻居丢失** | OSPF/BGP neighbor DOWN 未恢复 | WARNING |
| **批量事件** | >10 条相同类型事件 (1h内) | WARNING |
| **严重事件** | severity <= 3 | CRITICAL |
| **重启事件** | 非计划重启 | CRITICAL |

## Output Format

有异常需上报:
```json
{
  "device": "R1",
  "status": "warning",
  "event_count": 5,
  "events": [
    {
      "type": "ospf_neighbor_down",
      "severity": "warning",
      "count": 3,
      "neighbors": ["10.1.1.2", "10.1.1.3"],
      "first_seen": "2026-01-13T02:15:00Z",
      "last_seen": "2026-01-13T05:30:00Z",
      "recovered": false,
      "detail": "3个OSPF邻居DOWN超过5分钟未恢复"
    }
  ]
}
```

无异常:
```json
{
  "device": "R2",
  "status": "ok",
  "event_count": 0,
  "events": []
}
```
"""

    # =============================================================================
    # Reduce Phase: generate_report
    # =============================================================================

    async def generate_report(
        self,
        inspect_summary: dict[str, Any],
        log_summary: dict[str, Any],
        topology_path: str,
    ) -> str:
        """Reduce phase: Generate final Markdown report.

        This method performs global correlation analysis and generates
        a comprehensive daily report in Markdown format.

        Args:
            inspect_summary: Aggregated inspect summary from map_tools.aggregate_inspect_maps
            log_summary: Aggregated log summary from map_tools.aggregate_log_maps
            topology_path: Path to topology HTML file

        Returns:
            Markdown formatted daily report

        Examples:
            >>> report = await llm.generate_report(inspect_summ, log_summ, "topology.html")
            >>> print(report[:100])
            "# 网络日报 - 2026-01-13\\n\\n## 📊 执行摘要..."
        """
        # Load skill prompt
        skill_prompt = self._load_report_skill()

        # Build prompt with summaries
        inspect_json = json.dumps(inspect_summary, indent=2, ensure_ascii=False)
        log_json = json.dumps(log_summary, indent=2, ensure_ascii=False)

        prompt = f"""
{skill_prompt}

## Input Data

### 检查摘要
{inspect_json}

### 日志摘要
{log_json}

### 拓扑可视化
链接: [./{topology_path}](./{topology_path})

## Task

基于以上摘要数据，生成一份结构化的网络日报。
要求：
1. 执行摘要：设备总数、异常设备数、检查项统计
2. 问题列表：按优先级排序，包含关联分析和建议
3. 引用拓扑图
4. 使用中文输出

输出格式：纯Markdown（不要代码块）
"""

        # Retry logic
        for attempt in range(self.retry_count):
            try:
                messages = [SystemMessage(content=prompt)]
                response = await self.llm.ainvoke(messages)

                # Parse response
                content = response.content.strip()

                # Remove markdown code blocks if present
                if content.startswith("```markdown"):
                    content = content[11:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                return content

            except Exception:
                if attempt < self.retry_count - 1:
                    import asyncio

                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    # Fallback: generate basic report
                    return self._generate_fallback_report(
                        inspect_summary, log_summary, topology_path
                    )

    def _load_report_skill(self) -> str:
        """Load daily-report skill prompt.

        Returns:
            Skill prompt content
        """
        skill_path = Path(".olav/skills/daily-report/SKILL.md")
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
        else:
            # Fallback: built-in prompt
            return """
## Daily Report Generation

Generate a structured network daily report in Markdown format.

### Report Structure

1. **执行摘要**
   - 设备总数
   - 异常设备数
   - 检查项统计 (总数/正常/警告/严重)

2. **🗺️ 网络拓扑**
   - 引用: [查看完整拓扑](./topology.html)

3. **🔴 需要关注的问题**
   - 按优先级排序 (CRITICAL > WARNING)
   - 每个问题包含：
     * 现象描述
     * 根因分析
     * 影响评估
     * 处理建议

4. **详细数据** (可选，放在 <details> 标签内)
   - 完整检查结果列表
   - 完整事件列表

### Correlation Analysis Guidelines

- CPU 高 + OSPF DOWN → 路由抖动导致
- CRC 错误 + BGP reset → 物理层问题导致路由问题
- 多设备同时告警 → 可能网络事件
- 温度高 + 风扇失败 → 散热系统问题

### Report Template

```markdown
# 网络日报 - {{date}}

## 📊 执行摘要

| 指标 | 值 | 状态 |
|------|-----|------|
| 设备总数 | {{count}} | {{status}} |
| 异常设备 | {{anomaly_count}} | {{anomaly_status}} |
| 检查项正常率 | {{ok_rate}}% | {{ok_status}} |

## 🗺️ 网络拓扑

[查看完整拓扑](./topology.html)

## 🔴 需要关注的问题

### 1. {{title}} (CRITICAL)

**现象**: {{symptom}}

**根因**: {{root_cause}}

**影响**: {{impact}}

**建议**: {{recommendation}}

---

<details>
<summary>详细数据</summary>

### 检查结果详情

{{detailed_checks}}

### 事件详情

{{detailed_events}}

</details>
```
"""

    def _generate_fallback_report(
        self,
        inspect_summary: dict[str, Any],
        log_summary: dict[str, Any],
        topology_path: str,
    ) -> str:
        """Generate basic report without LLM.

        Args:
            inspect_summary: Inspect summary
            log_summary: Log summary
            topology_path: Path to topology

        Returns:
            Markdown report
        """
        date = datetime.now().strftime("%Y-%m-%d")

        summary = inspect_summary.get("summary", {})
        total_checks = summary.get("total_checks", 0)
        status_counts = summary.get("status_counts", {})
        ok_count = status_counts.get("ok", 0)
        warning_count = status_counts.get("warning", 0)
        critical_count = status_counts.get("critical", 0)

        anomalies = inspect_summary.get("anomalies", [])
        log_anomalies = log_summary.get("anomalies", [])

        lines = [
            f"# 网络日报 - {date}",
            "",
            "> ⚠️ LLM 分析不可用，仅显示统计数据",
            "",
            "## 📊 执行摘要",
            "",
            f"- 设备总数: {summary.get('total_devices', 0)}",
            f"- 异常设备: {len(set(a['device'] for a in anomalies))}",
            f"- 检查项总数: {total_checks}",
            f"  - ✅ 正常: {ok_count}",
            f"  - ⚠️  警告: {warning_count}",
            f"  - 🔴 严重: {critical_count}",
            "",
            "## 🗺️ 网络拓扑",
            "",
            f"[查看完整拓扑](./{topology_path})",
            "",
            "## 异常列表",
            "",
        ]

        if anomalies:
            lines.append("### 检查项异常")
            lines.append("")
            lines.append("| 设备 | 检查项 | 状态 | 值 | 说明 |")
            lines.append("|------|--------|------|-----|------|")

            for a in anomalies:
                device = a.get("device", "")
                check = a.get("check", "")
                status = a.get("status", "")
                value = a.get("value", "-")
                detail = a.get("detail", "-")

                status_icon = "🔴" if status == "critical" else "⚠️"
                lines.append(
                    f"| {device} | {check} | {status_icon} {status} | {value} | {detail} |"
                )

        if log_anomalies:
            lines.append("")
            lines.append("### 日志事件异常")
            lines.append("")

            for a in log_anomalies:
                device = a.get("device", "")
                events = a.get("events", [])
                lines.append(f"#### {device}")

                for event in events:
                    etype = event.get("type", "")
                    detail = event.get("detail", "")
                    lines.append(f"- **{etype}**: {detail}")

        return "\n".join(lines)
