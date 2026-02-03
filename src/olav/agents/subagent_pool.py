"""SubAgent Instance Pool - P3优化.

通过维护SubAgent实例池，避免每次查询都重新创建SubAgent。

优化效果:
- SubAgent创建成本: ~30-35ms per query
- 省时: 相比不缓存可节省30-35ms每次查询

实现原理:
1. 维护一个dict，以agent_type为key存储实例
2. 每种类型（database, cli, analysis）只创建一个实例
3. 使用线程锁保证线程安全
4. 支持clear()用于测试和重启
"""

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class SubAgentPool:
    """SubAgent实例缓存池.

    P3优化: 避免每次查询都创建新的SubAgent实例

    特点:
    - 线程安全
    - 每种类型维持单一实例
    - 支持清空和重置
    """

    _instances: dict[str, Any] = {}
    _lock = threading.Lock()
    _initialized: bool = False

    @classmethod
    def get_agent(cls, agent_type: str) -> Any:
        """获取或创建SubAgent实例.

        Args:
            agent_type: Agent类型 ("database", "cli", "analysis", etc)

        Returns:
            SubAgent实例 (同一类型返回同一实例)
        """
        # 快速路径: 如果已存在则直接返回
        if agent_type in cls._instances:
            return cls._instances[agent_type]

        # 缓存未命中, 获取锁后创建
        with cls._lock:
            # 双重检查锁: 再次确认未被其他线程创建
            if agent_type not in cls._instances:
                from olav.agents.orchestrator import _create_subagents

                # 创建所有SubAgent
                subagents = _create_subagents()

                # 按名称索引
                for agent in subagents:
                    cls._instances[agent.name] = agent
                    logger.debug(f"Created SubAgent: {agent.name}")

        return cls._instances.get(agent_type)

    @classmethod
    def clear(cls) -> None:
        """清空实例池.

        注意: 仅用于测试或重启场景
        """
        with cls._lock:
            cls._instances.clear()
            logger.info("SubAgent pool cleared")

    @classmethod
    def get_stats(cls) -> dict[str, int]:
        """获取实例池统计.

        Returns:
            包含实例数量的字典
        """
        return {
            "total_instances": len(cls._instances),
            "agent_types": list(cls._instances.keys()),
        }


def initialize_subagent_pool() -> None:
    """初始化SubAgent实例池.

    在应用启动时调用此方法以预加载SubAgent实例。
    这样所有后续查询都可以直接使用缓存的实例。

    预加载成本: ~50-100ms (一次性)
    """
    logger.info("Initializing SubAgent pool...")

    # 预加载所有SubAgent类型
    agent_types = ["database", "cli", "analysis"]
    for agent_type in agent_types:
        agent = SubAgentPool.get_agent(agent_type)
        if agent:
            logger.debug(f"✅ Preloaded SubAgent: {agent_type}")

    stats = SubAgentPool.get_stats()
    logger.info(f"SubAgent pool initialized: {stats['total_instances']} agents")
