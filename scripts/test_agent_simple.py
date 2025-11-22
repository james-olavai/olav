"""简化的 Agent 测试 - 查询设备接口状态"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from olav.core.llm import LLMFactory
from olav.core.prompt_manager import prompt_manager
from olav.core.settings import settings as env_settings
from olav.agents.cli_agent import create_cli_subagent

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)


async def test_simple_cli_query():
    """测试简单的 CLI 查询 - 直接使用 CLI Agent"""
    
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试场景: 使用 CLI Agent 查询设备接口状态")
    logger.info("=" * 80)
    
    try:
        # 1. 创建 LLM
        logger.info("\n🔧 创建 LLM 实例...")
        model = LLMFactory.get_chat_model()
        logger.info(f"✓ 模型: {model.model_name}")
        
        # 2. 创建 PostgreSQL Checkpointer
        logger.info("\n📡 连接 PostgreSQL Checkpointer...")
        postgres_uri = env_settings.postgres_uri
        if not postgres_uri:
            postgres_uri = f"postgresql://{env_settings.postgres_user}:{env_settings.postgres_password}@localhost:55432/{env_settings.postgres_db}"
        
        logger.info(f"URI: {postgres_uri.split('@')[0]}@...")
        
        async with AsyncPostgresSaver.from_conn_string(postgres_uri) as checkpointer:
            logger.info("✓ Checkpointer 创建成功")
            
            # 3. 创建 CLI SubAgent
            logger.info("\n🤖 创建 CLI SubAgent...")
            cli_subagent = create_cli_subagent()
            logger.info(f"✓ SubAgent: {cli_subagent['name']}")
            logger.info(f"  工具: {cli_subagent['tools']}")
            
            # 4. 创建 Root Agent (仅包含 CLI)
            logger.info("\n🌟 创建 Root Agent...")
            
            system_prompt = """你是网络运维助手 OLAV。

用户请求查询设备接口状态。你有一个 CLI 执行工具可用。

请直接调用 cli_tool 工具执行 'show ip interface brief' 命令来查询接口状态。

不要创建TODO列表，直接执行命令即可。
"""
            
            agent = create_deep_agent(
                model=model,
                system_prompt=system_prompt,
                checkpointer=checkpointer,
                subagents=[cli_subagent],
            )
            
            logger.info("✓ Root Agent 创建成功")
            
            # 5. 执行查询
            logger.info("\n📞 执行查询...")
            logger.info("-" * 80)
            
            device = "R1"
            query = "查询接口状态"
            
            logger.info(f"设备: {device}")
            logger.info(f"查询: {query}")
            logger.info("")
            
            # 构建消息
            user_message = f"请在设备 {device} 上{query}"
            
            # 配置 thread_id - 使用时间戳确保唯一性
            import time
            config = {
                "configurable": {
                    "thread_id": f"test-cli-query-{int(time.time())}"
                }
            }
            
            # 执行
            logger.info("正在调用 Agent...")
            
            # Use simple ainvoke
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=user_message)]},
                config=config
            )
            
            # 6. 显示结果
            logger.info("\n" + "=" * 80)
            logger.info("📊 执行结果")
            logger.info("=" * 80)
            
            messages = result.get("messages", [])
            
            logger.info(f"\n消息数量: {len(messages)}")
            
            for idx, msg in enumerate(messages, 1):
                logger.info(f"\n消息 {idx} ({msg.__class__.__name__}):")
                logger.info("-" * 80)
                
                if hasattr(msg, 'content'):
                    content = msg.content
                    if isinstance(content, str):
                        # 限制输出长度
                        preview = content[:500] if len(content) > 500 else content
                        logger.info(preview)
                        if len(content) > 500:
                            logger.info(f"\n... (共 {len(content)} 字符)")
                    else:
                        logger.info(content)
                
                # 显示工具调用
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    logger.info(f"\n🔧 工具调用:")
                    for tool_call in msg.tool_calls:
                        logger.info(f"  - {tool_call.get('name', 'unknown')}")
                        logger.info(f"    参数: {tool_call.get('args', {})}")
            
            # 最终回复
            final_message = messages[-1] if messages else None
            if final_message:
                logger.info("\n" + "=" * 80)
                logger.info("✅ 最终回复")
                logger.info("=" * 80)
                logger.info(final_message.content if hasattr(final_message, 'content') else str(final_message))
            
            logger.info("\n🎉 测试完成！")
            return True
            
    except Exception as e:
        logger.error(f"\n❌ 测试失败: {e}", exc_info=True)
        return False


async def main():
    """主函数"""
    logger.info("\n" + "=" * 80)
    logger.info("🚀 OLAV Agent 简化测试")
    logger.info("=" * 80)
    
    # 检查环境变量
    logger.info("\n📋 环境检查:")
    logger.info(f"  LLM Provider: {env_settings.llm_provider}")
    logger.info(f"  LLM Model: {env_settings.llm_model_name}")
    logger.info(f"  NetBox URL: {env_settings.netbox_url}")
    logger.info(f"  Device User: {env_settings.device_username}")
    
    success = await test_simple_cli_query()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    # Windows 需要使用 SelectorEventLoop
    import platform
    if platform.system() == "Windows":
        import selectors
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
