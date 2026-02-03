"""
网络相关性判断模块

用于 Guard Tier 2: 判断用户查询是否与网络运维相关
- 使用轻量 LLM 快速判断（0.3-0.5s）
- 礼貌拒绝非相关查询
- 触发动态学习机制
"""

import logging

from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)

# 极简 prompt，快速判断
RELEVANCE_CHECK_PROMPT = """你是网络运维助手 OLAV 的守门人。
判断用户查询是否与【网络设备、网络运维、网络配置、网络故障】相关。

用户查询: "{query}"

仅回答 YES 或 NO，不要解释。
- YES: 与网络运维相关
- NO: 与网络运维无关"""

POLITE_REJECTION = """抱歉，我是 **OLAV 网络运维助手**，专门帮助您处理：
- 🔧 网络设备状态查询
- 📊 网络性能分析
- 🔍 故障诊断与排查
- 📋 配置检查与对比

您的问题 "{query}" 似乎不在我的专业范围内。

如果您有网络相关的问题，请随时问我！"""


async def check_network_relevance(query: str, timeout: float = 1.0) -> tuple[bool, str | None]:
    """
    检查查询是否与网络相关

    Args:
        query: 用户查询
        timeout: LLM 调用超时时间（秒）

    Returns:
        (is_relevant, rejection_message)
        - (True, None): 相关，继续执行
        - (False, message): 不相关，返回拒绝消息
    """
    try:
        llm = LLMFactory.get_chat_model()

        prompt = RELEVANCE_CHECK_PROMPT.format(query=query)

        # 使用 timeout 控制
        import asyncio
        response = await asyncio.wait_for(
            llm.ainvoke(prompt),
            timeout=timeout
        )

        answer = response.content.strip().upper()

        if answer.startswith("YES"):
            logger.info(f"✅ Network relevance check: PASS - {query[:50]}")
            return (True, None)
        else:
            rejection = POLITE_REJECTION.format(query=query)
            logger.info(f"❌ Network relevance check: REJECT - {query[:50]}")
            return (False, rejection)

    except TimeoutError:
        logger.warning(f"⏱️ Network relevance check timeout ({timeout}s), allowing query: {query[:50]}")
        # 超时时允许查询（保守策略）
        return (True, None)
    except Exception as e:
        logger.error(f"❗ Network relevance check error: {e}, allowing query: {query[:50]}")
        # 出错时允许查询（保守策略）
        return (True, None)
