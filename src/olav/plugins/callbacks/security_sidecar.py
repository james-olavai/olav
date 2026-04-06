"""SecuritySidecarPlugin — LLM response policy monitor (旁路安全监控).

Observes every LLM completion via ``on_llm_end`` and scans the output text
for configurable policy violation patterns (prompt injection, jailbreak
attempts, sensitive-data leakage, etc.).

Design principles
-----------------
- **Zero-intrusion**: observer only — never modifies tool calls or blocks
  execution.  Violations are logged and written to the audit trail.
- **Configurable patterns**: rules are loaded from
  ``.olav/config/security_sidecar.yaml`` on first use (falls back to
  sensible built-in defaults when the file is absent).
- **Audit integration**: every violation is recorded through
  ``AuditEventRecorder`` with ``event_type="security_violation"``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.outputs import LLMResult

from olav.plugins.base import OLAVCallbackPlugin

logger = logging.getLogger("olav.security")

# ---------------------------------------------------------------------------
# Built-in violation pattern catalogue (regex strings)
# ---------------------------------------------------------------------------

_DEFAULT_PATTERNS: list[dict[str, str]] = [
    # Jailbreak / identity override
    {
        "id": "ignore-prev-instructions",
        "severity": "high",
        "pattern": r"(?i)(ignore\s+(all\s+)?previous\s+instructions|disregard\s+(your\s+)?system\s+prompt)",
        "description": "Prompt injection: override previous instructions",
    },
    {
        "id": "act-as-jailbreak",
        "severity": "high",
        "pattern": r"(?i)(you\s+are\s+now|pretend\s+you\s+are|act\s+as)\s+(dan|jailbreak|evil|uncensored|unfiltered|free\s+ai)",
        "description": "Identity override / DAN-style jailbreak",
    },
    {
        "id": "developer-mode",
        "severity": "high",
        "pattern": r"(?i)(developer\s+mode|god\s+mode|unrestricted\s+mode|bypass\s+(safety|filter|guardrail))",
        "description": "Mode-switching jailbreak",
    },
    # Sensitive data exfiltration signals
    {
        "id": "cred-pattern-aws",
        "severity": "critical",
        "pattern": r"AKIA[0-9A-Z]{16}",
        "description": "Potential AWS access key in LLM output",
    },
    {
        "id": "cred-pattern-private-key",
        "severity": "critical",
        "pattern": r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "description": "Private key material in LLM output",
    },
    # System prompt extraction
    {
        "id": "system-prompt-extraction",
        "severity": "medium",
        "pattern": r"(?i)(reveal|print|output|show|repeat|display)\s+(your|the)\s+system\s+prompt",
        "description": "Attempt to extract system prompt",
    },
]


def _load_patterns() -> list[dict[str, str]]:
    """Load patterns from config file or fall back to built-in defaults."""
    try:
        from olav.core.config import get_paths_config

        config_root = get_paths_config().config_dir
        rules_file = config_root / "security_sidecar.yaml"
        if rules_file.exists():
            import yaml  # type: ignore[import-untyped]

            with open(rules_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            rules = data.get("patterns", [])
            if rules:
                logger.debug("SecuritySidecar: loaded %d rules from %s", len(rules), rules_file)
                return rules
    except Exception:
        pass
    return _DEFAULT_PATTERNS


def _compile_patterns(rules: list[dict[str, str]]) -> list[tuple[str, str, re.Pattern[str]]]:
    compiled = []
    for rule in rules:
        try:
            compiled.append((
                rule.get("id", "unknown"),
                rule.get("severity", "medium"),
                re.compile(rule["pattern"], re.MULTILINE),
            ))
        except re.error as exc:
            logger.warning("SecuritySidecar: invalid pattern %r — %s", rule.get("id"), exc)
    return compiled


class SecuritySidecarPlugin(OLAVCallbackPlugin):
    """Bypass security monitor: scans LLM output for policy violations.

    This plugin is a pure observer — it never interrupts execution.  Detected
    violations are emitted as ``WARNING`` log messages and recorded in the
    audit trail for later review.

    Args:
        recorder: Optional ``AuditEventRecorder``.  Defaults to a new
            recorder backed by ``AUDIT_DB_PATH``.
        extra_patterns: Additional ``{"id", "severity", "pattern"}`` dicts
            appended to the loaded rule set.
    """

    name = "security_sidecar"
    version = "1.0.0"
    description = "旁路安全监控：扫描 LLM 输出中的策略违规（jailbreak / 数据泄露）"
    tags = ["builtin", "security", "sidecar"]

    def __init__(
        self,
        recorder: Any = None,
        extra_patterns: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__()
        if recorder is None:
            try:
                from olav.core.audit_recorder import AuditEventRecorder

                recorder = AuditEventRecorder()
            except Exception:
                recorder = None
        self._recorder = recorder

        rules = _load_patterns()
        if extra_patterns:
            rules = rules + extra_patterns
        self._patterns = _compile_patterns(rules)
        logger.debug("SecuritySidecar: %d compiled rules", len(self._patterns))

    def _scan(self, text: str) -> list[dict[str, str]]:
        """Return list of violation dicts found in *text*."""
        violations: list[dict[str, str]] = []
        for rule_id, severity, pattern in self._patterns:
            match = pattern.search(text)
            if match:
                violations.append({
                    "rule_id": rule_id,
                    "severity": severity,
                    "matched": match.group(0)[:120],
                })
        return violations

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Scan all generation outputs for policy violations."""
        for generations in response.generations:
            for gen in generations:
                text: str = getattr(gen, "text", "") or ""
                if not text:
                    # ChatGeneration stores content on the message
                    msg = getattr(gen, "message", None)
                    if msg is not None:
                        text = getattr(msg, "content", "") or ""
                if not text:
                    continue
                violations = self._scan(text)
                if not violations:
                    continue
                for v in violations:
                    logger.warning(
                        "SecuritySidecar violation [%s/%s] match=%r",
                        v["severity"].upper(),
                        v["rule_id"],
                        v["matched"],
                    )
                if self._recorder is not None:
                    try:
                        await self._record_violations(violations, text[:500])
                    except Exception as exc:
                        logger.debug("SecuritySidecar: audit record failed — %s", exc)

    async def _record_violations(
        self, violations: list[dict[str, str]], text_snippet: str
    ) -> None:
        import asyncio
        import json

        payload = json.dumps(
            {
                "violations": violations,
                "text_snippet": text_snippet,
            },
            ensure_ascii=False,
        )
        await asyncio.get_event_loop().run_in_executor(
            None,
            self._recorder.record,
            "security_violation",
            payload,
        )
