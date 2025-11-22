"""Test Agent using DeepAgents official pattern - create_agent + SubAgentMiddleware"""

import asyncio
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from olav.core.llm import LLMFactory
from olav.core.settings import settings as env_settings
from olav.tools.nornir_tool import cli_tool, netconf_tool
from deepagents.middleware.subagents import SubAgentMiddleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)


async def test_agent_official_pattern():
    """使用 DeepAgents 官方推荐模式测试 Agent"""
    
    logger.info("\n" + "=" * 80)
    logger.info("🧪 OLAV Agent 测试 (官方 SubAgent 模式)")
    logger.info("=" * 80)
    
    logger.info("\n📋 环境检查:")
    logger.info(f"  LLM Provider: {env_settings.llm_provider}")
    logger.info(f"  LLM Model: {env_settings.llm_model_name}")
    logger.info(f"  NetBox URL: {env_settings.netbox_url}")
    logger.info(f"  Device User: {env_settings.device_username}")
    
    try:
        # 1. Create LLM
        logger.info("\n🔧 创建 LLM 实例...")
        model = LLMFactory.get_chat_model()
        logger.info(f"✓ 模型: {env_settings.llm_model_name}")
        
        # 2. Create PostgreSQL checkpointer
        logger.info("\n📡 连接 PostgreSQL Checkpointer...")
        postgres_uri = env_settings.postgres_uri
        masked_uri = postgres_uri.replace(env_settings.postgres_uri.split('@')[0].split(':')[-1], '...')
        logger.info(f"URI: {masked_uri}")
        
        async with AsyncPostgresSaver.from_conn_string(postgres_uri) as checkpointer:
            logger.info("✓ Checkpointer 创建成功")
            
            # 3. Define SubAgents (官方模式)
            logger.info("\n🤖 创建 SubAgents...")
            
            # CLI SubAgent
            cli_subagent = {
                "name": "cli-executor",
                "description": "专门处理 CLI 命令执行的 SubAgent，使用 SSH Netmiko 连接设备",
                "system_prompt": """你是 CLI 命令执行专家。

**职责**: 通过 SSH (Netmiko) 执行设备 CLI 命令

**可用工具**:
- cli_tool: 执行 show 命令（自动 TextFSM 解析）或配置命令（需要 HITL 审批）

**工作流程**:
1. 确定目标设备和命令
2. 使用 cli_tool 执行
3. 返回结构化结果

**示例**:
用户: "查询 R1 接口状态"
操作: cli_tool(device="R1", command="show ip interface brief")
返回: 解析后的接口列表
""",
                "tools": [cli_tool],
                "model": model,  # 使用相同模型
            }
            
            # NETCONF SubAgent
            netconf_subagent = {
                "name": "netconf-executor",
                "description": "专门处理 NETCONF 操作的 SubAgent，支持 OpenConfig 模型",
                "system_prompt": """你是 NETCONF 操作专家。

**职责**: 通过 NETCONF 协议与网络设备交互

**可用工具**:
- netconf_tool: 执行 get-config/edit-config 操作

**重要**: 如果 NETCONF 连接失败，返回明确错误信息，Root Agent 会自动降级到 CLI

**工作流程**:
1. 构造 XPath 查询或 XML payload
2. 使用 netconf_tool 执行
3. 如果失败，返回错误（触发降级）

**示例**:
成功: netconf_tool(device="R1", operation="get-config", xpath="/interfaces/interface")
失败: 返回 "NETCONF connection failed: Connection refused on port 830"
""",
                "tools": [netconf_tool],
                "model": model,
            }
            
            logger.info(f"✓ 定义了 2 个 SubAgent: cli-executor, netconf-executor")
            
            # 4. Create Agent with SubAgentMiddleware (官方模式)
            logger.info("\n🌟 创建 Root Agent (官方模式)...")
            
            system_prompt = """你是企业网络运维专家 OLAV (Omni-Layer Autonomous Verifier)。

**架构**: 你是 Root Agent，负责任务编排和降级决策

**可用 SubAgent**:
1. **netconf-executor**: NETCONF 协议专家（优先使用）
2. **cli-executor**: CLI 命令专家（NETCONF 失败时降级）

**工作流程 (漏斗式排错)**:
1. 分析用户查询意图
2. 优先尝试 NETCONF (更精确、结构化)
3. 如果 NETCONF 失败，降级到 CLI
4. 综合结果，提供清晰回复

**降级触发条件**:
- NETCONF 返回错误消息包含 "Connection refused" 或 "Timeout"
- 设备不支持 NETCONF (端口 830 关闭)

**示例**:
用户: "查询 R1 接口状态"
步骤1: 调用 netconf-executor → 失败 (Connection refused)
步骤2: 降级到 cli-executor → 成功
返回: 基于 CLI 结果的总结
"""
            
            # 使用官方推荐的 create_agent + SubAgentMiddleware
            agent = create_agent(
                model=model,
                system_prompt=system_prompt,
                middleware=[
                    TodoListMiddleware(),  # Root Agent 的 TODO 管理
                    SubAgentMiddleware(
                        default_model=model,
                        default_tools=[],  # 不使用默认工具
                        default_middleware=[],  # ⚠️ 关键：不使用默认 middleware (避免 PatchToolCalls 干扰)
                        subagents=[cli_subagent, netconf_subagent],
                        general_purpose_agent=False,  # 不需要通用 SubAgent
                    ),
                ],
                checkpointer=checkpointer,
            )
            
            logger.info("✓ Root Agent 创建成功")
            logger.info("  Middleware: TodoListMiddleware, SubAgentMiddleware")
            logger.info("  SubAgents: 2 个专用 SubAgent")
            
            # 5. Execute query
            logger.info("\n📞 执行测试查询...")
            logger.info("-" * 80)
            
            device = "R1"
            query = "查询接口状态"
            
            logger.info(f"设备: {device}")
            logger.info(f"查询: {query}")
            logger.info("")
            
            user_message = f"请在设备 {device} 上{query}"
            
            # 使用唯一 thread_id
            import time
            config = {
                "configurable": {
                    "thread_id": f"official-pattern-{int(time.time())}"
                }
            }
            
            logger.info("正在调用 Agent (可能需要 30-60 秒)...")
            
            # 使用 astream 查看进度
            logger.info("\n开始流式执行...")
            logger.info("=" * 80)
            
            final_state = None
            step_count = 0
            
            async for chunk in agent.astream(
                {"messages": [HumanMessage(content=user_message)]},
                config=config,
                stream_mode="updates"
            ):
                step_count += 1
                logger.info(f"\n步骤 {step_count}:")
                
                # 显示更新的节点
                for node_name, node_data in chunk.items():
                    logger.info(f"  节点: {node_name}")
                    
                    if "messages" in node_data:
                        messages_in_step = node_data["messages"]
                        if messages_in_step:
                            last_msg = messages_in_step[-1]
                            logger.info(f"    类型: {last_msg.__class__.__name__}")
                            
                            if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                                for tc in last_msg.tool_calls:
                                    logger.info(f"    调用: {tc['name']}")
                    
                    final_state = node_data
            
            logger.info(f"\n总步骤数: {step_count}")
            
            # Get final result
            result = await agent.aget_state(config)
            logger.info(f"\n✓ Agent 执行完成")
            
            # 6. Display results
            logger.info("\n" + "=" * 80)
            logger.info("📊 执行结果")
            logger.info("=" * 80)
            
            messages = result.values.get("messages", [])
            
            logger.info(f"\n消息数量: {len(messages)}")
            
            for idx, msg in enumerate(messages, 1):
                msg_type = msg.__class__.__name__
                logger.info(f"\n消息 {idx} ({msg_type}):")
                logger.info("-" * 80)
                
                if hasattr(msg, 'content'):
                    content = str(msg.content)
                    if len(content) > 300:
                        logger.info(content[:300] + "...")
                    else:
                        logger.info(content)
                
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    logger.info("\n🔧 工具调用:")
                    for tc in msg.tool_calls:
                        logger.info(f"  - {tc['name']}")
                        args = tc.get('args', {})
                        if len(str(args)) > 200:
                            logger.info(f"    参数: {str(args)[:200]}...")
                        else:
                            logger.info(f"    参数: {args}")
            
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
    logger.info("🚀 OLAV Agent 官方模式测试")
    logger.info("=" * 80)
    
    success = await test_agent_official_pattern()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    # Windows 需要 SelectorEventLoop
    import platform
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
