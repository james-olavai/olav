"""Test Agent with direct tool registration - NO SubAgent"""

import asyncio
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from olav.core.llm import LLMFactory
from olav.core.settings import settings as env_settings
from olav.tools.nornir_tool import cli_tool
from deepagents import create_deep_agent

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)


async def test_agent_direct_tools():
    """Test Agent with tools registered directly (no SubAgent delegation)"""
    
    logger.info("\n" + "=" * 80)
    logger.info("🧪 OLAV Agent 直接工具测试 (无SubAgent)")
    logger.info("=" * 80)
    
    logger.info("\n📋 环境检查:")
    logger.info(f"  LLM Provider: {env_settings.llm_provider}")
    logger.info(f"  LLM Model: {env_settings.llm_model_name}")
    logger.info(f"  NetBox URL: {env_settings.netbox_url}")
    logger.info(f"  Device User: {env_settings.device_username}")
    
    try:
        # Create LLM
        logger.info("\n🔧 创建 LLM 实例...")
        model = LLMFactory.get_chat_model()
        logger.info(f"✓ 模型: {env_settings.llm_model_name}")
        
        # Create PostgreSQL checkpointer
        logger.info("\n📡 连接 PostgreSQL Checkpointer...")
        postgres_uri = env_settings.postgres_uri
        # Mask password in log
        masked_uri = postgres_uri.replace(env_settings.postgres_uri.split('@')[0].split(':')[-1], '...')
        logger.info(f"URI: {masked_uri}")
        
        async with AsyncPostgresSaver.from_conn_string(postgres_uri) as checkpointer:
            logger.info("✓ Checkpointer 创建成功")
            
            # Create Agent with direct tool registration
            logger.info("\n🤖 创建 Agent (直接注册工具)...")
            
            system_prompt = """你是企业网络运维专家 OLAV。

**可用工具**:
- cli_tool: 在网络设备上执行 CLI 命令 (SSH Netmiko)

**任务**: 帮助用户查询网络设备状态。

**工作流程**:
1. 理解用户查询意图
2. 确定目标设备和命令
3. 使用 cli_tool 执行命令
4. 解析并呈现结果

**示例**:
用户: "查询 R1 的接口状态"
操作: cli_tool(device="R1", command="show ip interface brief")
"""
            
            agent = create_deep_agent(
                model=model,
                system_prompt=system_prompt,
                tools=[cli_tool],  # Direct registration
                checkpointer=checkpointer,
            )
            
            logger.info("✓ Agent 创建成功")
            logger.info(f"  工具: {[tool.name for tool in [cli_tool]]}")
            
            # Execute query
            logger.info("\n📞 执行查询...")
            logger.info("-" * 80)
            
            device = "R1"
            query = "查询接口状态"
            
            logger.info(f"设备: {device}")
            logger.info(f"查询: {query}")
            logger.info("")
            
            user_message = f"请在设备 {device} 上{query}"
            logger.info(f"正在调用 Agent...")
            
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=user_message)]},
                config={"configurable": {"thread_id": "test-session-no-subagent"}}
            )
            
            # Display results
            logger.info("\n" + "=" * 80)
            logger.info("📊 执行结果")
            logger.info("=" * 80)
            
            messages = result.get("messages", [])
            logger.info(f"\n消息数量: {len(messages)}")
            
            for idx, msg in enumerate(messages, 1):
                msg_type = msg.__class__.__name__
                logger.info(f"\n消息 {idx} ({msg_type}):")
                logger.info("-" * 80)
                
                if hasattr(msg, 'content'):
                    content = str(msg.content)[:200]
                    logger.info(content)
                
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    logger.info("\n🔧 工具调用:")
                    for tc in msg.tool_calls:
                        logger.info(f"  - {tc['name']}")
                        logger.info(f"    参数: {tc.get('args', {})}")
            
            # Extract final answer
            final_message = messages[-1] if messages else None
            if final_message and hasattr(final_message, 'content'):
                logger.info("\n" + "=" * 80)
                logger.info("✅ 最终回复")
                logger.info("=" * 80)
                logger.info(final_message.content)
            
            logger.info("\n🎉 测试完成！")
            return True
            
    except Exception as e:
        logger.error(f"\n❌ 测试失败: {e}", exc_info=True)
        return False


async def main():
    logger.info("\n" + "=" * 80)
    logger.info("🚀 OLAV Agent 直接工具测试")
    logger.info("=" * 80)
    
    success = await test_agent_direct_tools()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    # Windows 需要 SelectorEventLoop
    import platform
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
