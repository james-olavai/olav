"""Quality Check Middleware - SubAgent结果质量评估与Expert升级

此中间件在SubAgent执行后评估结果质量，决定是否升级到Expert Agent:
1. 检查结果完整性（空结果、错误、信息不足）
2. 检查用户意图（是否需要高级分析）
3. 检查复杂度（是否需要跨设备关联、根因分析）
4. 自动升级到Expert Agent处理高级问题

使用方式:
    from olav.middleware.quality_check import QualityCheckMiddleware

    middleware = [QualityCheckMiddleware()]
    agent = create_deep_agent(..., middleware=middleware)
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class QualityEvaluator:
    """评估 SubAgent 结果质量，决定是否需要升级到 Expert Agent"""

    # 需要高级分析的关键词
    ANALYSIS_KEYWORDS = [
        "为什么",
        "原因",
        "根因",
        "root cause",
        "why",
        "investigate",
        "analyze",
        "diagnosis",
        "troubleshoot",
        "分析",
        "诊断",
        "排查",
    ]

    # 跨设备关联的关键词
    CROSS_DEVICE_KEYWORDS = [
        "对比",
        "比较",
        "所有设备",
        "全网",
        "compare",
        "all devices",
        "cross-device",
        "between",
        "之间",
        "差异",
    ]

    # 拓扑分析关键词
    TOPOLOGY_KEYWORDS = [
        "拓扑",
        "邻居",
        "连接",
        "topology",
        "neighbor",
        "peer",
        "connection",
        "path",
        "trace",
        "路径",
    ]

    def should_upgrade_to_expert(
        self,
        user_query: str,
        subagent_name: str,
        subagent_result: str,
        execution_time: float = 0.0,
    ) -> tuple[bool, str]:
        """判断是否需要升级到 Expert Agent

        Args:
            user_query: 用户原始查询
            subagent_name: 执行的SubAgent名称 (query/cli/analysis)
            subagent_result: SubAgent返回的结果
            execution_time: SubAgent执行耗时（秒）

        Returns:
            (should_upgrade, reason) - 是否升级及原因
        """
        query_lower = user_query.lower()

        # 规则 1: 结果为空或包含错误 → 升级
        if not subagent_result or len(subagent_result.strip()) == 0:
            return True, "SubAgent returned empty result"

        if any(
            err in subagent_result.lower()
            for err in ["error", "failed", "无法", "没有找到", "not found"]
        ):
            # 排除友好的"没有发现异常"消息
            if "没有发现异常" in subagent_result or "no anomalies" in subagent_result.lower():
                return False, "Normal 'no anomalies' message"
            return True, "SubAgent result contains error or failure"

        # 规则 2: 用户明确要求高级分析 → 直接升级
        if any(kw in query_lower for kw in self.ANALYSIS_KEYWORDS):
            return True, "User explicitly requested investigation/analysis"

        # 规则 3: 需要跨设备关联分析 → 升级（排除简单列表）
        is_simple_list = subagent_name == "query" and any(
            kw in query_lower for kw in ["list", "列出", "show", "显示", "count", "多少个"]
        )
        if not is_simple_list and any(kw in query_lower for kw in self.CROSS_DEVICE_KEYWORDS):
            return True, "Query requires cross-device correlation"

        # 规则 4: 需要拓扑分析 → 升级
        if any(kw in query_lower for kw in self.TOPOLOGY_KEYWORDS):
            return True, "Query requires topology awareness"

        # 规则 5: 结果过短可能信息不足 → 升级（但排除缓存命中）
        if len(subagent_result) < 100 and "cached" not in subagent_result.lower():
            # 排除正常的简短回答（如设备列表）
            if subagent_name == "query" and any(
                kw in query_lower
                for kw in ["list", "列出", "show", "显示", "多少", "count", "所有", "all"]
            ):
                return False, "Simple list query - short result is normal"
            return True, "SubAgent result too brief, may be insufficient"

        # 规则 6: SubAgent执行时间过长 → 可能遇到问题，升级
        if execution_time > 30.0:  # 30秒超时
            return True, f"SubAgent execution timeout ({execution_time:.1f}s > 30s)"

        # 所有检查通过，不需要升级
        return False, "Result quality acceptable, no upgrade needed"


class QualityCheckMiddleware:
    """质量检查中间件 - 在SubAgent执行后评估质量

    使用DeepAgents中间件模式，在SubAgent调用后拦截结果:
    1. 评估SubAgent结果质量
    2. 如果质量不足，自动升级到Expert Agent
    3. 记录升级决策日志

    Note: 此中间件设计用于DeepAgents架构，但当前Orchestrator
    使用的是create_deep_agent()，暂不支持自定义中间件链。

    TODO: 在Orchestrator中手动实现质量检查逻辑，或等待DeepAgents
    支持自定义中间件。
    """

    def __init__(self) -> None:
        """初始化质量检查中间件"""
        self.evaluator = QualityEvaluator()
        self.upgrade_count = 0
        self.evaluation_count = 0

    async def __call__(self, state: dict[str, Any], next_step: Any) -> dict[str, Any]:
        """中间件调用入口

        Args:
            state: 当前状态
            next_step: 下一步执行函数

        Returns:
            处理后的状态
        """
        # 执行SubAgent
        import time

        start_time = time.time()
        result = await next_step(state)
        execution_time = time.time() - start_time

        self.evaluation_count += 1

        # 提取信息用于评估
        messages = result.get("messages", [])
        if not messages:
            return result

        # 获取用户查询和SubAgent回复
        user_query = messages[0].content if messages else ""
        subagent_result = messages[-1].content if len(messages) > 1 else ""
        subagent_name = result.get("active_subagent", "unknown")

        # 评估质量
        should_upgrade, reason = self.evaluator.should_upgrade_to_expert(
            user_query=user_query,
            subagent_name=subagent_name,
            subagent_result=subagent_result,
            execution_time=execution_time,
        )

        if should_upgrade:
            self.upgrade_count += 1
            logger.warning(
                f"🔼 Quality check failed, upgrading to Expert Agent "
                f"(reason: {reason}, count: {self.upgrade_count}/{self.evaluation_count})"
            )

            # TODO: 调用Expert SubAgent
            # 当前DeepAgents架构中，无法直接在中间件中重新路由
            # 需要在Orchestrator的system_prompt中指导升级逻辑

            # 临时方案: 在result中添加升级标记，让Orchestrator决策
            result["_quality_check"] = {
                "should_upgrade": True,
                "reason": reason,
                "original_subagent": subagent_name,
            }
        else:
            logger.debug(
                f"✅ Quality check passed: {reason} "
                f"(evaluations: {self.evaluation_count}, upgrades: {self.upgrade_count})"
            )
            result["_quality_check"] = {
                "should_upgrade": False,
                "reason": reason,
            }

        return result

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息

        Returns:
            统计数据字典
        """
        return {
            "evaluation_count": self.evaluation_count,
            "upgrade_count": self.upgrade_count,
            "upgrade_rate": (
                self.upgrade_count / self.evaluation_count if self.evaluation_count > 0 else 0.0
            ),
        }


# =============================================================================
# Standalone Functions (用于非中间件模式)
# =============================================================================


def evaluate_result_quality(
    user_query: str,
    subagent_name: str,
    subagent_result: str,
    execution_time: float = 0.0,
) -> dict[str, Any]:
    """独立函数版本的质量评估（用于直接调用）

    Args:
        user_query: 用户原始查询
        subagent_name: 执行的SubAgent名称
        subagent_result: SubAgent返回的结果
        execution_time: 执行耗时

    Returns:
        评估结果字典:
        {
            "should_upgrade": bool,
            "reason": str,
            "subagent_name": str,
        }
    """
    evaluator = QualityEvaluator()
    should_upgrade, reason = evaluator.should_upgrade_to_expert(
        user_query=user_query,
        subagent_name=subagent_name,
        subagent_result=subagent_result,
        execution_time=execution_time,
    )

    return {
        "should_upgrade": should_upgrade,
        "reason": reason,
        "subagent_name": subagent_name,
        "execution_time": execution_time,
    }
