"""
示例：集成 Guard 和缓存到 Orchestrator

这是一个示例文件，展示如何将 Guard 和统一缓存集成到 Orchestrator
实际的 orchestrator.py 文件较复杂，建议在 CLI 入口处集成 Guard
"""

import asyncio
import logging
from typing import Any

from config.settings import Settings
from olav.agents.relevance_checker import check_network_relevance
from olav.cache import cache, init_cache

logger = logging.getLogger(__name__)

# 启动时初始化缓存
init_cache()


async def orchestrate_with_guard(query: str) -> dict[str, Any]:
    """
    完整请求处理流程（带 Guard 和缓存）

    Tier 0   → Guard 静态黑名单（可关闭）
    Tier 0.5 → Guard 动态拒绝缓存（可关闭）
    Tier 1   → Intent 缓存（可调整置信度）
    Tier 2   → 主 Agent 网络相关性判断（可关闭）
    Tier 3   → LLM 执行

    Args:
        query: 用户查询

    Returns:
        执行结果字典
    """
    settings = Settings()

    # ==================== Tier 0: 静态黑名单 ====================
    if settings.guard.enabled and settings.guard.check_blacklist:
        blocked, reason = cache.check_blacklist(query)
        if blocked:
            return {"status": "blocked", "message": reason}

    # ==================== Tier 0.5: 动态拒绝缓存 ====================
    if settings.guard.enabled and settings.guard.enable_dynamic_learning:
        rejected, rejection_msg = cache.check_rejected(query)
        if rejected:
            return {"status": "rejected", "message": rejection_msg}

    # ==================== Tier 1: Intent 缓存 ====================
    # 主路由使用 fuzzy 模式（容错）
    cached_result = cache.get_intent(
        query,
        match_mode=settings.routing.cache_match_mode,  # fuzzy
        confidence_threshold=settings.routing.cache_confidence_threshold,  # 0.85
    )
    if cached_result:
        logger.info(f"✅ Cache HIT (confidence={cached_result.get('_confidence', 1.0):.2f})")
        return {
            "status": "cached",
            "result": cached_result,
            "confidence": cached_result.get("_confidence"),
            "match_mode": cached_result.get("_match_mode"),
        }

    # ==================== Tier 2: 网络相关性判断 ====================
    if settings.guard.enabled and settings.guard.check_network_relevance:
        is_relevant, rejection = await check_network_relevance(
            query, timeout=settings.guard.relevance_check_timeout
        )

        if not is_relevant:
            # 动态学习：写入拒绝缓存
            if settings.guard.enable_dynamic_learning:
                cache.add_rejected(query, rejection)
            return {"status": "rejected", "message": rejection}

    # ==================== Tier 3: LLM 执行 ====================
    # 这里调用实际的 Orchestrator
    # from olav.agents.orchestrator import Orchestrator
    # result = await Orchestrator().orchestrate(query)
    result = {"status": "success", "message": "模拟执行成功（请替换为实际 Orchestrator 调用）"}

    # 缓存成功结果
    if result.get("status") == "success":
        cache.set_intent(query, result)

    return result


# ==================== CLI 集成示例 ====================


async def cli_handle_query(query: str) -> str:
    """
    CLI 入口处理查询（集成 Guard）

    Args:
        query: 用户查询

    Returns:
        Markdown 格式响应
    """
    result = await orchestrate_with_guard(query)

    if result["status"] == "blocked":
        return f"## ⛔ 安全拦截\n\n{result['message']}"

    elif result["status"] == "rejected":
        return result["message"]  # 礼貌拒绝消息已经是 Markdown

    elif result["status"] == "cached":
        confidence = result.get("confidence", 1.0)
        match_mode = result.get("match_mode", "exact")

        confidence_tag = ""
        if match_mode == "fuzzy" and confidence < 0.95:
            confidence_tag = f" 🟡 相似度: {confidence:.1%}"

        return f"## ⚡ 缓存结果{confidence_tag}\n\n{result['result'].get('message', '无响应')}"

    else:
        return f"## ✅ 执行成功\n\n{result.get('message', '无响应')}"


if __name__ == "__main__":
    # 测试示例
    async def test() -> None:
        print("=== 测试 1: 网络查询（应该通过）===")
        result = await cli_handle_query("查看 R1 的状态")
        print(result)
        print()

        print("=== 测试 2: 非网络查询（应该被拒绝）===")
        result = await cli_handle_query("帮我写一首诗")
        print(result)
        print()

        print("=== 测试 3: 重复非网络查询（应该直接拒绝，无需 LLM）===")
        result = await cli_handle_query("帮我写一首诗")
        print(result)
        print()

        print("=== 测试 4: 危险命令（应该被黑名单拦截）===")
        result = await cli_handle_query("drop table devices")
        print(result)

    asyncio.run(test())
