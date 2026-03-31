"""
approval.py — 网络危险命令审批门

在 execute_cli 执行路径中检测高风险的 config-mode 命令（破坏性操作、
协议删除、接口关闭等），返回结构化的审批结果供 agent 决策。

设计原则:
  - 非阻断式: 返回 ApprovalResult，由调用方决定是阻断还是升级为 HITL
  - 只检测写操作（configure terminal 类命令）
  - read-only 命令（show、display、get）不触发审批
  - 规则列表可通过 .olav/config/approval_rules.yaml 扩展（未来）

参考: dev_docs/15. hermes.md §3.2
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── 危险命令模式 ───────────────────────────────────────────────────────────────
# 每条规则: (pattern, severity, description)
# severity: "high" = 直接阻断建议；"medium" = 警告建议

_DANGEROUS_RULES: list[tuple[str, str, str]] = [
    # ── 设备生命周期 ────────────────────────────────────────────────────────
    (r"(?i)^\s*reload\b", "high", "Device reload — will cause network outage"),
    (r"(?i)^\s*shutdown\s*$", "high", "System shutdown command"),
    (r"(?i)^\s*reload\s+in\b", "high", "Scheduled reload — will cause network outage"),

    # ── 配置清除 ─────────────────────────────────────────────────────────────
    (r"(?i)\bwrite\s+erase\b", "high", "Erases startup config — irreversible without backup"),
    (r"(?i)\berase\s+startup-config\b", "high", "Erases startup config"),
    (r"(?i)\berase\s+nvram\b", "high", "Erases NVRAM — irreversible without backup"),
    (r"(?i)\bformat\s+(flash|disk|bootflash)\b", "high", "Format filesystem — data loss"),
    (r"(?i)\bdelete\s+.*\.(cfg|conf|bin)\b", "high", "Delete config/binary file"),

    # ── 路由协议删除 ─────────────────────────────────────────────────────────
    (r"(?i)^\s*no\s+router\s+(bgp|ospf|isis|eigrp|rip)\b", "high",
     "Remove routing protocol — may cause network-wide reachability loss"),
    (r"(?i)^\s*no\s+ip\s+routing\b", "high",
     "Disable IP routing — host-only mode, all routed traffic lost"),
    (r"(?i)^\s*no\s+router-id\b", "medium", "Remove router-id — BGP/OSPF sessions may reset"),

    # ── 接口关闭 ─────────────────────────────────────────────────────────────
    (r"(?i)^\s*shutdown\s*$", "high", "Interface shutdown — brings link down"),
    (r"(?i)^\s*interface\s+\S+.*\n\s*shutdown", "high",
     "Interface + shutdown sequence — brings link down"),

    # ── AAA / 访问控制 ───────────────────────────────────────────────────────
    (r"(?i)^\s*no\s+aaa\s+new-model\b", "high",
     "Disable AAA — may lock out all management access"),
    (r"(?i)^\s*no\s+ip\s+ssh\b", "medium", "Disable SSH — remote management loss"),
    (r"(?i)^\s*no\s+username\s+\w", "medium", "Remove local user — may lock out access"),

    # ── SRL / Nokia SR Linux 特有 ───────────────────────────────────────────
    (r"(?i)^\s*delete\s+.*network-instance", "high",
     "Delete network-instance — routing table and all its routes removed"),
    (r"(?i)^\s*delete\s+.*interface\s+\S+", "medium",
     "Delete interface config — may cause connectivity loss"),

    # ── 通用 Linux / shell（防止通过 exec 执行） ─────────────────────────────
    (r"(?i)\brm\s+-[a-z]*rf?\b", "high", "Recursive force delete — irreversible data loss"),
    (r"(?i)\bdd\s+.*of=/dev/", "high", "Raw disk write — irreversible"),
    (r"(?i)\bmkfs\b", "high", "Filesystem format — irreversible data loss"),
]

# read-only 前缀白名单（命中则直接放行，不检查危险规则）
_READONLY_PREFIXES = re.compile(
    r"(?i)^\s*(show|display|get|list|describe|print|type|cat|more|less|"
    r"ping|traceroute|tracert|nslookup|dig|whois|curl\s+.*-[gG]|"
    r"info|status|version|who|w\s|id\s|uptime)\b"
)

_COMPILED_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(pattern), severity, description)
    for pattern, severity, description in _DANGEROUS_RULES
]


# ── 结果类型 ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ApprovalResult:
    """危险命令检测结果。

    Attributes:
        requires_approval: True 表示命令需要审批
        severity: "high" | "medium" | None
        reason: 人类可读的危险原因
        matched_pattern: 命中的正则表达式（调试用）
        suggested_action: 给 agent 的建议操作
    """
    requires_approval: bool
    severity: str | None = None
    reason: str | None = None
    matched_pattern: str | None = None
    suggested_action: str = field(default="")

    def __post_init__(self) -> None:
        if self.requires_approval and not self.suggested_action:
            object.__setattr__(
                self,
                "suggested_action",
                (
                    "This command requires operator approval before execution. "
                    "Use record_hitl_requested() to escalate to a human operator, "
                    "or confirm with the user before proceeding."
                ),
            )


# ── 公开 API ──────────────────────────────────────────────────────────────────

def check_approval(command: str, device: str = "") -> ApprovalResult:
    """检查命令是否需要人工审批。

    在 execute_cli_main() 的黑名单校验之后、Nornir 执行之前调用。

    Args:
        command: 待执行的 CLI 命令字符串
        device:  目标设备名（仅用于错误信息，不影响判断逻辑）

    Returns:
        ``ApprovalResult(requires_approval=False)`` — 安全，可直接执行
        ``ApprovalResult(requires_approval=True, ...)`` — 需要审批，工具应返回
        ``{"status": "requires_approval", "reason": ..., "suggested_action": ...}``

    Example::

        result = check_approval("no router bgp 65000", device="R1")
        if result.requires_approval:
            return {
                "status": "requires_approval",
                "device": device,
                "command": command,
                "severity": result.severity,
                "reason": result.reason,
                "suggested_action": result.suggested_action,
            }
    """
    if not command or not command.strip():
        return ApprovalResult(requires_approval=False)

    # read-only 命令直接放行
    if _READONLY_PREFIXES.match(command):
        return ApprovalResult(requires_approval=False)

    # 逐规则检查
    for pattern, severity, description in _COMPILED_RULES:
        if pattern.search(command):
            device_hint = f" on {device}" if device else ""
            return ApprovalResult(
                requires_approval=True,
                severity=severity,
                reason=f"{description}{device_hint}",
                matched_pattern=pattern.pattern,
            )

    return ApprovalResult(requires_approval=False)
