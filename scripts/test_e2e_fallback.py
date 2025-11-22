"""
端到端测试：NETCONF 失败 → CLI 自动降级流程

测试场景:
1. 用户请求: "查询 R1 的接口状态"
2. Root Agent → NETCONF Agent (尝试 NETCONF)
3. NETCONF 失败 (Connection Refused)
4. Root Agent 检测到错误 → 更新计划
5. Root Agent → CLI Agent (降级到 CLI)
6. CLI Agent 成功执行 "show ip interface brief"
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# 设置 PYTHONPATH (添加 src 和 config 目录)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))  # 添加项目根目录以支持 config 导入

from deepagents import create_deep_agent
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver

from olav.core.llm import LLMFactory
from olav.core.prompt_manager import prompt_manager
from olav.agents.suzieq_agent import create_suzieq_subagent
from olav.agents.rag_agent import create_rag_subagent
from olav.agents.netconf_agent import create_netconf_subagent
from olav.agents.cli_agent import create_cli_subagent

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger(__name__)


async def test_netconf_to_cli_fallback():
    """测试 NETCONF 失败后自动降级到 CLI"""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 端到端测试：NETCONF → CLI 自动降级")
    logger.info("=" * 80)
    
    # 1. 检查必需环境变量
    required_env = ["POSTGRES_URI", "LLM_PROVIDER", "LLM_API_KEY"]
    missing_env = [var for var in required_env if not os.getenv(var)]
    
    if missing_env:
        logger.error(f"❌ 缺少环境变量: {missing_env}")
        logger.info("请在 .env 文件中配置以下变量:")
        logger.info("  POSTGRES_URI=postgresql://olav:OlavPG123!@localhost:5432/olav")
        logger.info("  LLM_PROVIDER=openai")
        logger.info("  LLM_API_KEY=sk-...")
        return False
    
    # 2. 创建 SubAgents
    try:
        logger.info("\n📦 创建 SubAgents...")
        suzieq_subagent = create_suzieq_subagent()
        rag_subagent = create_rag_subagent()
        netconf_subagent = create_netconf_subagent()
        cli_subagent = create_cli_subagent()
        logger.info(f"  ✓ SuzieQ Agent: {suzieq_subagent['name']}")
        logger.info(f"  ✓ RAG Agent: {rag_subagent['name']}")
        logger.info(f"  ✓ NETCONF Agent: {netconf_subagent['name']}")
        logger.info(f"  ✓ CLI Agent: {cli_subagent['name']}")
    except Exception as e:
        logger.error(f"❌ SubAgent 创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 3. 创建 Root Agent
    try:
        logger.info("\n🤖 创建 Root Agent...")
        
        # 获取 LLM
        model = LLMFactory.get_chat_model()
        
        # 创建 PostgreSQL Checkpointer
        checkpointer = PostgresSaver.from_conn_string(os.getenv("POSTGRES_URI"))
        
        # 加载 Root Agent Prompt (带降级策略)
        root_prompt = prompt_manager.load_agent_prompt(
            "root_agent",
            user_name="测试用户",
            network_context="测试环境: R1 (可能不支持 NETCONF)"
        )
        
        # 追加降级策略到 Prompt
        fallback_strategy = """
        
## NETCONF → CLI 自动降级策略

**执行顺序**:
1. 优先尝试 **netconf-executor** (标准化、原子回滚)
2. 如果 NETCONF 返回错误包含 "connection failed" 或 "Connection refused":
   - 更新计划: "NETCONF 不可用，降级到 CLI 方案"
   - 调用 **cli-executor** 完成相同任务
3. 如果 CLI 也失败，向用户报告并请求指导

**关键**: 不要预先探测端口，让工具自然失败并返回错误信息。
"""
        root_prompt_with_fallback = root_prompt + fallback_strategy
        
        # 创建 Root Agent
        agent = create_deep_agent(
            model=model,
            system_prompt=root_prompt_with_fallback,
            checkpointer=checkpointer,
            subagents=[
                suzieq_subagent,
                rag_subagent,
                netconf_subagent,
                cli_subagent
            ]
        )
        logger.info("  ✓ Root Agent 创建成功")
        logger.info(f"  - SubAgents: {len(agent.subagents)} 个")
        logger.info(f"  - Checkpointer: PostgreSQL")
        
    except Exception as e:
        logger.error(f"❌ Root Agent 创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 4. 执行测试场景
    try:
        logger.info("\n🎯 测试场景: 查询 R1 的接口状态")
        logger.info("  预期行为:")
        logger.info("    1. Root Agent → NETCONF Agent")
        logger.info("    2. NETCONF 失败 (Connection Refused)")
        logger.info("    3. Root Agent 检测错误 → 切换到 CLI Agent")
        logger.info("    4. CLI Agent 成功执行")
        
        # 构造测试消息
        test_message = HumanMessage(
            content="查询 R1 路由器的接口状态 (假设 R1 地址是 192.168.1.1，不支持 NETCONF)"
        )
        
        # 配置执行上下文 (使用独立的 thread)
        config = {
            "configurable": {
                "thread_id": "test-netconf-cli-fallback"
            }
        }
        
        logger.info("\n▶️  开始执行...")
        logger.info("-" * 80)
        
        # 执行 Agent (流式输出)
        final_state = None
        async for event in agent.astream_events(
            {"messages": [test_message]},
            config=config,
            version="v2"
        ):
            # 打印关键事件
            kind = event.get("event")
            
            if kind == "on_chat_model_stream":
                # LLM 输出流
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content"):
                    content = chunk.content
                    if content:
                        print(content, end="", flush=True)
            
            elif kind == "on_tool_start":
                # 工具调用开始
                tool_name = event.get("name")
                tool_input = event.get("data", {}).get("input")
                logger.info(f"\n🔧 调用工具: {tool_name}")
                logger.info(f"   输入: {tool_input}")
            
            elif kind == "on_tool_end":
                # 工具调用结束
                tool_name = event.get("name")
                tool_output = event.get("data", {}).get("output")
                logger.info(f"\n✓ 工具完成: {tool_name}")
                logger.info(f"   输出: {tool_output[:200] if isinstance(tool_output, str) else tool_output}...")
        
        logger.info("\n" + "-" * 80)
        logger.info("✓ 执行完成")
        
        # 5. 验证结果
        logger.info("\n📊 验证测试结果...")
        
        # 获取最终状态
        final_state = await agent.aget_state(config)
        messages = final_state.values.get("messages", [])
        
        logger.info(f"  消息数量: {len(messages)}")
        
        # 检查是否有 NETCONF 失败的证据
        netconf_failed = False
        cli_executed = False
        
        for msg in messages:
            content = str(msg.content) if hasattr(msg, "content") else str(msg)
            if "NETCONF connection failed" in content or "Connection refused" in content:
                netconf_failed = True
                logger.info("  ✓ 检测到 NETCONF 失败")
            if "cli_tool" in content or "show ip interface" in content:
                cli_executed = True
                logger.info("  ✓ 检测到 CLI 工具调用")
        
        # 判断测试结果
        if netconf_failed and cli_executed:
            logger.info("\n🎉 测试通过！")
            logger.info("  ✓ NETCONF 失败被正确处理")
            logger.info("  ✓ CLI Agent 自动接管")
            return True
        else:
            logger.warning("\n⚠️  测试未完全符合预期")
            logger.info(f"  NETCONF 失败: {netconf_failed}")
            logger.info(f"  CLI 执行: {cli_executed}")
            logger.info("\n💡 提示: 这可能是因为:")
            logger.info("  1. Mock 环境未正确配置 NETCONF 失败")
            logger.info("  2. Agent 直接选择了 CLI (未尝试 NETCONF)")
            logger.info("  3. 需要真实设备环境测试")
            return False
        
    except Exception as e:
        logger.error(f"❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试入口"""
    logger.info("\n" + "=" * 80)
    logger.info("🚀 OLAV 端到端测试套件")
    logger.info("=" * 80)
    
    # 运行测试
    success = await test_netconf_to_cli_fallback()
    
    # 输出总结
    logger.info("\n" + "=" * 80)
    logger.info("测试总结")
    logger.info("=" * 80)
    
    if success:
        logger.info("✅ 端到端测试通过")
        logger.info("\n下一步:")
        logger.info("  1. 在真实设备上测试 (GNS3/EVE-NG)")
        logger.info("  2. 测试 HITL 审批流程")
        logger.info("  3. 测试多设备并发场景")
    else:
        logger.info("❌ 端到端测试失败")
        logger.info("\n建议:")
        logger.info("  1. 检查环境变量配置")
        logger.info("  2. 确认 PostgreSQL 可用")
        logger.info("  3. 使用真实设备测试完整流程")
    
    return success


if __name__ == "__main__":
    asyncio.run(main())
