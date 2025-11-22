"""Test Full OLAV Stack: SuzieQ → NETCONF/CLI (Funnel Debugging)"""

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
from olav.tools.suzieq_tool import suzieq_query, suzieq_schema_search
from deepagents.middleware.subagents import SubAgentMiddleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)


async def test_full_stack():
    """测试完整 OLAV 技术栈：SuzieQ 宏观分析 + NETCONF/CLI 微观诊断"""
    
    logger.info("\n" + "=" * 80)
    logger.info("🧪 OLAV 完整技术栈测试 (漏斗式排错)")
    logger.info("=" * 80)
    
    logger.info("\n📋 环境检查:")
    logger.info(f"  LLM: {env_settings.llm_model_name}")
    logger.info(f"  NetBox: {env_settings.netbox_url}")
    logger.info(f"  SuzieQ: TODO - 需配置 SuzieQ context")
    
    try:
        # 1. Create LLM
        model = LLMFactory.get_chat_model()
        
        # 2. Create PostgreSQL checkpointer
        postgres_uri = env_settings.postgres_uri
        
        async with AsyncPostgresSaver.from_conn_string(postgres_uri) as checkpointer:
            
            # 3. Define ALL SubAgents (完整栈)
            logger.info("\n🤖 创建 SubAgents...")
            
            # SuzieQ SubAgent - 宏观分析
            suzieq_subagent = {
                "name": "suzieq-analyzer",
                "description": "网络宏观分析专家，使用 SuzieQ 查询网络拓扑、BGP、接口等聚合数据",
                "system_prompt": """你是网络宏观分析专家，使用 SuzieQ 进行网络状态分析。

**职责**: 快速识别网络范围的问题（宏观 → 微观）

**可用工具**:
- suzieq_schema_search: 搜索可用的 SuzieQ 表和字段
- suzieq_query: 查询网络数据（interfaces, bgp, routes, devices 等）

**工作流程** (Schema-Aware):
1. 用户查询 → 理解意图
2. suzieq_schema_search(query="查询目标相关的表") → 发现可用表
3. suzieq_query(table="发现的表", method="summarize") → 获取聚合数据
4. 返回宏观分析结果

**示例**:
用户: "检查网络中的接口问题"
步骤1: suzieq_schema_search(query="interfaces status") 
→ 发现 "interfaces" 表，字段包括 state, adminState, hostname

步骤2: suzieq_query(table="interfaces", method="summarize")
→ 返回所有设备接口状态汇总

步骤3: 分析结果，识别异常设备 → 建议 Root Agent 深入检查特定设备

**重要**: 
- SuzieQ 是只读分析，无法修改配置
- 用于快速定位问题范围，不查看详细配置
- 如需详细配置，建议 Root Agent 使用 NETCONF/CLI SubAgent
""",
                "tools": [suzieq_query, suzieq_schema_search],
                "model": model,
            }
            
            # CLI SubAgent
            cli_subagent = {
                "name": "cli-executor",
                "description": "CLI 命令执行专家，SSH Netmiko 连接",
                "system_prompt": """你是 CLI 命令执行专家。

**职责**: 通过 SSH 执行设备 CLI 命令（微观诊断）

**可用工具**:
- cli_tool: 执行 show 命令（自动 TextFSM 解析）

**工作流程**:
1. 接收 Root Agent 的任务（通常来自 SuzieQ 分析结果）
2. 使用 cli_tool 执行具体命令
3. 返回结构化结果

**示例**:
任务: "查询 R1 的接口详细配置（SuzieQ 显示该设备有接口 down）"
操作: cli_tool(device="R1", command="show ip interface brief")
返回: 解析后的接口列表 + 状态
""",
                "tools": [cli_tool],
                "model": model,
            }
            
            # NETCONF SubAgent
            netconf_subagent = {
                "name": "netconf-executor",
                "description": "NETCONF 操作专家，支持 OpenConfig",
                "system_prompt": """你是 NETCONF 操作专家。

**职责**: 通过 NETCONF 协议与设备交互（微观诊断/配置）

**可用工具**:
- netconf_tool: 执行 get-config/edit-config

**重要**: 如果 NETCONF 连接失败，明确返回错误，Root Agent 会降级到 CLI

**工作流程**:
1. 接收 Root Agent 的任务
2. 构造 XPath 或 XML payload
3. 使用 netconf_tool 执行
4. 如果失败，返回错误（触发降级）

**示例**:
任务: "获取 R1 接口配置（OpenConfig 格式）"
操作: netconf_tool(device="R1", operation="get-config", xpath="/interfaces/interface")
失败返回: "NETCONF connection failed: Connection refused on port 830"
""",
                "tools": [netconf_tool],
                "model": model,
            }
            
            logger.info(f"✓ 定义了 3 个 SubAgent: suzieq-analyzer, cli-executor, netconf-executor")
            
            # 4. Create Root Agent (完整编排逻辑)
            logger.info("\n🌟 创建 Root Agent (漏斗式排错)...")
            
            system_prompt = """你是企业网络运维专家 OLAV (Omni-Layer Autonomous Verifier)。

**核心方法论**: 漏斗式排错（宏观 → 微观）

**架构**: 你是 Root Agent，负责任务编排和降级决策

**可用 SubAgent**:
1. **suzieq-analyzer**: 网络宏观分析（优先使用，快速定位）
2. **netconf-executor**: NETCONF 微观诊断（次优先）
3. **cli-executor**: CLI 微观诊断（NETCONF 失败时降级）

**标准工作流程**（漏斗式 3 步）:

### 步骤 1: 宏观分析（SuzieQ）
- 用户查询 → 调用 suzieq-analyzer
- 获取网络范围的状态概览
- 识别异常设备/链路/协议

**示例**:
用户: "网络有问题吗？"
你: 调用 suzieq-analyzer → 查询 interfaces, bgp, routes 表
结果: "发现设备 R1 有 2 个接口 down"

### 步骤 2: 微观诊断（NETCONF 优先）
- 基于宏观分析结果，深入检查特定设备
- 优先尝试 netconf-executor（生产标准）
- 如果失败（Connection refused），降级到 cli-executor

**示例**:
宏观结果: "R1 有接口问题"
你: 调用 netconf-executor(device="R1", operation="get-config", xpath="/interfaces")
失败 → 降级到 cli-executor(device="R1", command="show running-config interface")

### 步骤 3: 综合结果
- 整合宏观 + 微观数据
- 提供清晰的根因分析
- 建议解决方案

**降级触发条件**:
- NETCONF 返回 "Connection refused" 或 "Timeout" → 切换到 CLI
- CLI 也失败 → 检查设备可达性

**关键原则**:
1. 先宏观后微观（避免盲目查询单设备）
2. 先 NETCONF 后 CLI（优先结构化）
3. 快速定位，精准诊断
"""
            
            # 使用官方推荐的 create_agent + SubAgentMiddleware
            agent = create_agent(
                model=model,
                system_prompt=system_prompt,
                middleware=[
                    TodoListMiddleware(),
                    SubAgentMiddleware(
                        default_model=model,
                        default_tools=[],
                        default_middleware=[],  # ⚠️ 避免 PatchToolCalls
                        subagents=[suzieq_subagent, cli_subagent, netconf_subagent],
                        general_purpose_agent=False,
                    ),
                ],
                checkpointer=checkpointer,
            )
            
            logger.info("✓ Root Agent 创建成功")
            logger.info("  完整技术栈: SuzieQ → NETCONF/CLI")
            
            # 5. Execute query
            logger.info("\n📞 执行测试查询...")
            logger.info("-" * 80)
            
            # 测试场景：需要宏观 + 微观分析
            query = "检查网络中是否有设备接口问题，如果有，请深入分析 R1 设备"
            
            logger.info(f"查询: {query}")
            logger.info("")
            
            # 使用唯一 thread_id
            import time
            config = {
                "configurable": {
                    "thread_id": f"full-stack-{int(time.time())}"
                }
            }
            
            logger.info("正在调用 Agent (完整流程可能需要 60-90 秒)...")
            logger.info("预期流程: SuzieQ 宏观分析 → 发现问题 → NETCONF/CLI 微观诊断")
            logger.info("\n开始流式执行...")
            logger.info("=" * 80)
            
            step_count = 0
            message_count = 0
            
            async for chunk in agent.astream(
                {"messages": [HumanMessage(content=query)]},
                config=config,
                stream_mode="updates"
            ):
                step_count += 1
                logger.info(f"\n步骤 {step_count}:")
                
                for node_name, node_data in chunk.items():
                    logger.info(f"  节点: {node_name}")
                    
                    if "messages" in node_data:
                        for msg in node_data["messages"]:
                            message_count += 1
                            msg_type = type(msg).__name__
                            logger.info(f"    消息类型: {msg_type}")
                            
                            # 显示工具调用
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    logger.info(f"      工具调用: {tc['name']}")
                                    logger.info(f"      参数: {tc.get('args', {})}")
                            
                            # 显示 SubAgent 任务
                            if msg_type == "AIMessage" and "task" in str(msg.content).lower():
                                logger.info(f"      SubAgent 任务: {msg.content[:200]}...")
            
            logger.info("\n" + "=" * 80)
            logger.info(f"执行完成！总步骤: {step_count}, 总消息: {message_count}")
            
            # 获取最终结果
            final_state = await agent.aget_state(config)
            
            logger.info("\n" + "=" * 80)
            logger.info("✅ 最终回复")
            logger.info("=" * 80)
            
            if final_state and final_state.values.get("messages"):
                final_message = final_state.values["messages"][-1]
                logger.info(final_message.content)
            
            logger.info("\n🎉 测试完成！")
            
            # 统计分析
            all_messages = final_state.values.get("messages", [])
            tool_calls = [
                msg for msg in all_messages 
                if hasattr(msg, "tool_calls") and msg.tool_calls
            ]
            
            logger.info(f"\n📊 执行统计:")
            logger.info(f"  总消息数: {len(all_messages)}")
            logger.info(f"  工具调用: {len(tool_calls)}")
            logger.info(f"  SubAgent 调用: {sum(1 for msg in all_messages if 'task' in str(getattr(msg, 'tool_calls', [])))}")
            
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # Windows: Use SelectorEventLoop for psycopg async compatibility
    import sys
    import selectors
    if sys.platform == "win32":
        asyncio.run(test_full_stack(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(test_full_stack())
