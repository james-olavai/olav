"""Query Router - Legacy compatibility layer.

NOTE: This module is kept for backward compatibility only.
- Guard: Moved to olav.core.guard
- Routing: Now handled by Orchestrator (LangGraph)

Use Guard class from olav.core.guard instead.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from olav.core.guard import Guard, GuardResult

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """路由决策结果."""

    expert: str | None  # database, cli, analysis, None表示拒绝或需要审批
    action: str  # route, reject, require_approval
    tool: str | None = None  # 具体调用的工具
    params: dict[str, Any] | None = None  # 提取的参数
    message: str | None = None  # 提示消息
    intent: str | None = None  # LLM分类的意图 (query, analysis, etc.)
    protocol: str | None = None  # Phase 15: 意图遮罩 (ospf, bgp, interface)
    timings: dict[str, float] | None = None  # 性能监控：各步骤耗时（秒）


class QueryRouter:
    """问题路由器 - Legacy compatibility layer.
    
    NOTE: Routing is now handled by Orchestrator (LangGraph).
    This class is kept only for Guard compatibility.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        guard: Guard | None = None,
    ) -> None:
        """初始化路由器.

        Args:
            config_path: Ignored (routing_rules.yaml no longer needed)
            guard: Guard实例，如果为None则自动创建
        """
        # 初始化Guard (独立的安全检查)
        self.guard = guard if guard is not None else Guard()

    def check_guard(self, user_input: str) -> GuardResult:
        """检查用户输入是否安全.

        Args:
            user_input: 用户输入

        Returns:
            GuardResult: 检查结果
        """
        return self.guard.check(user_input)

    def route(self, user_input: str) -> RoutingDecision:
        """DEPRECATED: Use Orchestrator instead.
        
        This method is kept for backward compatibility but is no longer used.
        Routing is now handled by LangGraph Orchestrator.
        """
        # Legacy route method - no longer used
        return RoutingDecision(
            expert="database",
            action="route",
            message="Legacy routing - use Orchestrator instead"
        )
