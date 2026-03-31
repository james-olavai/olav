"""
olav.platform.safety — 安全基线模块（开源版）

提供两个独立能力：
  - injection_scanner: 检测 prompt 注入尝试（用于 memory/knowledge 写入路径）
  - approval: 网络危险命令审批门（用于 execute_cli 执行路径）
"""

from olav.platform.safety.approval import ApprovalResult, check_approval
from olav.platform.safety.injection_scanner import InjectionMatch, scan_content

__all__ = [
    "scan_content",
    "InjectionMatch",
    "check_approval",
    "ApprovalResult",
]
