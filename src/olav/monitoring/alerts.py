"""Alert System - Phase 5 Day 7-8.

Monitors JSON structured logs and triggers alerts based on critical thresholds:
- Query latency alerts (>5s)
- Cache efficiency alerts (<50% hit rate)
- Error rate alerts (>10 errors/min)
- LLM usage alerts (excessive token consumption)
"""

import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass
class AlertRule:
    """Alert rule definition.

    Attributes:
        name: Rule name
        description: Human-readable description
        condition: Callable that returns True if alert should fire
        threshold: Threshold value for the condition
        window_seconds: Time window for metric aggregation
        cooldown_seconds: Minimum time between alerts
        severity: Alert severity level
    """

    name: str
    description: str
    condition: Callable[[dict], bool]
    threshold: float
    window_seconds: int
    cooldown_seconds: int = 300  # 5 minutes default
    severity: Literal["critical", "warning", "info"] = "warning"
    last_triggered: float = 0.0
    events: deque = field(default_factory=lambda: deque(maxlen=1000))


class AlertManager:
    """Alert manager for monitoring log events.

    Monitors structured logs and triggers alerts based on rules:
    - Maintains sliding windows for metrics
    - Respects cooldown periods
    - Supports multiple alert handlers (email, webhook, log)
    """

    def __init__(self):
        """Initialize alert manager."""
        self.rules: dict[str, AlertRule] = {}
        self.handlers: list[Callable[[str, str, dict], None]] = []
        self.logger = logging.getLogger(__name__)
        self._setup_default_rules()

    def _setup_default_rules(self):
        """Setup default alert rules."""
        # Query latency alert
        self.add_rule(
            AlertRule(
                name="query_latency_high",
                description="Query latency exceeds 5 seconds",
                condition=lambda events: self._check_latency(events, 5.0),
                threshold=5.0,
                window_seconds=60,
                cooldown_seconds=300,
                severity="warning",
            )
        )

        # Cache efficiency alert
        self.add_rule(
            AlertRule(
                name="cache_hit_rate_low",
                description="Cache hit rate below 50%",
                condition=lambda events: self._check_cache_hit_rate(events, 0.5),
                threshold=0.5,
                window_seconds=300,  # 5 minutes
                cooldown_seconds=600,  # 10 minutes
                severity="warning",
            )
        )

        # Error rate alert
        self.add_rule(
            AlertRule(
                name="error_rate_high",
                description="Error rate exceeds 10 errors per minute",
                condition=lambda events: self._check_error_rate(events, 10),
                threshold=10,
                window_seconds=60,
                cooldown_seconds=300,
                severity="critical",
            )
        )

        # LLM token usage alert
        self.add_rule(
            AlertRule(
                name="llm_tokens_high",
                description="LLM token usage exceeds 100k tokens per hour",
                condition=lambda events: self._check_llm_tokens(events, 100000),
                threshold=100000,
                window_seconds=3600,  # 1 hour
                cooldown_seconds=1800,  # 30 minutes
                severity="info",
            )
        )

    def add_rule(self, rule: AlertRule):
        """Add alert rule.

        Args:
            rule: Alert rule to add
        """
        self.rules[rule.name] = rule

    def add_handler(self, handler: Callable[[str, str, dict], None]):
        """Add alert handler.

        Args:
            handler: Callable(rule_name, message, context)
        """
        self.handlers.append(handler)

    def process_log_event(self, log_line: str):
        """Process a log event and check alert rules.

        Args:
            log_line: JSON log line
        """
        try:
            event = json.loads(log_line)
        except json.JSONDecodeError:
            return

        # Add timestamp if not present
        if "@timestamp" not in event:
            event["@timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Route event to relevant rules
        event_type = event.get("extra", {}).get("event")

        if event_type == "query_end":
            self._check_rule("query_latency_high", event)
        elif event_type in ["cache_hit", "cache_miss"]:
            self._check_rule("cache_hit_rate_low", event)
        elif event.get("level") == "ERROR":
            self._check_rule("error_rate_high", event)
        elif event_type == "llm_call":
            self._check_rule("llm_tokens_high", event)

    def _check_rule(self, rule_name: str, event: dict):
        """Check if rule should trigger.

        Args:
            rule_name: Rule name
            event: Log event
        """
        if rule_name not in self.rules:
            return

        rule = self.rules[rule_name]

        # Add timestamp to event if not present
        if "@timestamp" not in event:
            event["@timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Add current Unix timestamp for easier comparison
        event["_unix_time"] = self._parse_timestamp(event["@timestamp"])

        # Add event to sliding window
        rule.events.append(event)

        # Remove old events outside window
        cutoff = time.time() - rule.window_seconds
        while rule.events and rule.events[0].get("_unix_time", 0) < cutoff:
            rule.events.popleft()

        # Check cooldown
        if time.time() - rule.last_triggered < rule.cooldown_seconds:
            return

        # Evaluate condition
        if rule.condition(list(rule.events)):
            self._trigger_alert(rule, event)

    def _trigger_alert(self, rule: AlertRule, event: dict):
        """Trigger alert.

        Args:
            rule: Alert rule that triggered
            event: Log event that triggered the alert
        """
        rule.last_triggered = time.time()

        message = f"[{rule.severity.upper()}] {rule.description}"
        context = {
            "rule": rule.name,
            "severity": rule.severity,
            "threshold": rule.threshold,
            "window_seconds": rule.window_seconds,
            "event": event,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        # Log alert
        if rule.severity == "critical":
            self.logger.critical(message, extra={"alert": context})
        elif rule.severity == "warning":
            self.logger.warning(message, extra={"alert": context})
        else:
            self.logger.info(message, extra={"alert": context})

        # Call handlers
        for handler in self.handlers:
            try:
                handler(rule.name, message, context)
            except Exception as e:
                self.logger.error(f"Alert handler failed: {e}")

    @staticmethod
    def _parse_timestamp(ts: str) -> float:
        """Parse ISO timestamp to Unix time.

        Args:
            ts: ISO timestamp string or Unix timestamp

        Returns:
            Unix timestamp
        """
        if not ts:
            return time.time()

        # Handle Unix timestamp strings
        try:
            return float(ts)
        except (ValueError, TypeError):
            pass

        # Handle ISO format
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return time.time()

    def _check_latency(self, events: list[dict], threshold: float) -> bool:
        """Check if any query exceeds latency threshold.

        Args:
            events: List of query_end events
            threshold: Latency threshold in seconds

        Returns:
            True if alert should fire
        """
        for event in events:
            duration = event.get("extra", {}).get("duration_seconds", 0)
            if duration > threshold:
                return True
        return False

    def _check_cache_hit_rate(self, events: list[dict], threshold: float) -> bool:
        """Check if cache hit rate is below threshold.

        Args:
            events: List of cache_hit/cache_miss events
            threshold: Hit rate threshold (0.0-1.0)

        Returns:
            True if alert should fire
        """
        if not events:
            return False

        hits = sum(1 for e in events if e.get("extra", {}).get("event") == "cache_hit")
        total = len(events)

        if total < 10:  # Need at least 10 events
            return False

        hit_rate = hits / total
        return hit_rate < threshold

    def _check_error_rate(self, events: list[dict], threshold: int) -> bool:
        """Check if error rate exceeds threshold.

        Args:
            events: List of ERROR level events
            threshold: Error count threshold per window

        Returns:
            True if alert should fire
        """
        error_count = len([e for e in events if e.get("level") == "ERROR"])
        return error_count > threshold

    def _check_llm_tokens(self, events: list[dict], threshold: int) -> bool:
        """Check if LLM token usage exceeds threshold.

        Args:
            events: List of llm_call events
            threshold: Token count threshold per window

        Returns:
            True if alert should fire
        """
        total_tokens = sum(e.get("extra", {}).get("tokens", 0) for e in events)
        return total_tokens > threshold


# Global alert manager instance
_alert_manager = None


def get_alert_manager() -> AlertManager:
    """Get global alert manager instance.

    Returns:
        AlertManager instance
    """
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
        # Add default log handler
        _alert_manager.add_handler(log_alert_handler)
    return _alert_manager


def log_alert_handler(rule_name: str, message: str, context: dict):
    """Default alert handler that logs to file.

    Args:
        rule_name: Alert rule name
        message: Alert message
        context: Alert context
    """
    # Write to alerts log file
    alerts_log = Path("logs/alerts.json")
    alerts_log.parent.mkdir(parents=True, exist_ok=True)

    with open(alerts_log, "a", encoding="utf-8") as f:
        alert_event = {
            "timestamp": context["timestamp"],
            "rule": rule_name,
            "severity": context["severity"],
            "message": message,
            "context": context,
        }
        f.write(json.dumps(alert_event) + "\n")


def email_alert_handler(
    smtp_host: str,
    smtp_port: int,
    from_addr: str,
    to_addrs: list[str],
    username: str = "",
    password: str = "",
):
    """Create email alert handler.

    Args:
        smtp_host: SMTP server host
        smtp_port: SMTP server port
        from_addr: Sender email address
        to_addrs: List of recipient email addresses
        username: SMTP username (optional)
        password: SMTP password (optional)

    Returns:
        Email alert handler function
    """
    import smtplib
    from email.message import EmailMessage

    def handler(rule_name: str, message: str, context: dict):
        """Send alert email."""
        msg = EmailMessage()
        msg["Subject"] = f"OLAV Alert: {rule_name}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)

        body = f"""
Alert: {message}

Rule: {rule_name}
Severity: {context["severity"]}
Timestamp: {context["timestamp"]}
Threshold: {context["threshold"]}
Window: {context["window_seconds"]}s

Event Details:
{json.dumps(context["event"], indent=2)}
"""
        msg.set_content(body)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if username and password:
                server.starttls()
                server.login(username, password)
            server.send_message(msg)

    return handler


def webhook_alert_handler(webhook_url: str, headers: dict | None = None):
    """Create webhook alert handler.

    Args:
        webhook_url: Webhook URL
        headers: Optional HTTP headers

    Returns:
        Webhook alert handler function
    """
    import httpx

    def handler(rule_name: str, message: str, context: dict):
        """Send alert to webhook."""
        payload = {
            "rule": rule_name,
            "message": message,
            "severity": context["severity"],
            "timestamp": context["timestamp"],
            "context": context,
        }

        httpx.post(
            webhook_url,
            json=payload,
            headers=headers or {},
            timeout=5.0,
        )

    return handler
