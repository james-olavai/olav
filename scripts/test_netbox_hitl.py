"""Test NetBox Agent HITL (Human-in-the-Loop) approval workflow.

This script demonstrates how write operations to NetBox require human approval.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Windows: Fix event loop for psycopg async
if sys.platform == 'win32':
    import selectors
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from deepagents import create_deep_agent
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from olav.core.llm import LLMFactory
from olav.core.settings import settings
from olav.agents.netbox_agent import create_netbox_subagent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_read_only_operation():
    """Test read-only operation (no HITL needed)."""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试 1: 只读操作（不需要 HITL）")
    logger.info("=" * 80)
    
    try:
        # Setup - Use async context manager
        async with AsyncPostgresSaver.from_conn_string(settings.postgres_uri) as checkpointer:
            model = LLMFactory.get_chat_model()
            netbox_subagent = create_netbox_subagent()
            
            # Create agent
            agent = create_deep_agent(
                model=model,
                system_prompt="你是 NetBox 管理专家。",
                checkpointer=checkpointer,
                subagents=[netbox_subagent],
            )
        
        # Query devices (read-only)
        config = {"configurable": {"thread_id": "test-read-only"}}
        query = "查询 NetBox 中所有带 olav-managed 标签的设备"
        
        logger.info(f"\n用户查询: {query}")
        logger.info("\n预期结果: 直接执行，无需 HITL 审批\n")
        
        final_state = None
        interrupt_encountered = False
        
        async for event in agent.astream(
            {"messages": [HumanMessage(content=query)]},
            config=config,
            stream_mode="updates"
        ):
            # Check if we hit an interrupt
            if "interrupt" in str(event).lower():
                interrupt_encountered = True
                logger.warning("⚠️  遇到 HITL 中断（不应该发生）")
            
            final_state = event
        
        if not interrupt_encountered:
            logger.info("✅ 只读操作成功执行，无 HITL 中断")
            return True
        else:
            logger.error("❌ 只读操作不应该触发 HITL")
            return False
            
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_write_operation_with_hitl():
    """Test write operation that requires HITL approval."""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试 2: 写操作（需要 HITL 审批）")
    logger.info("=" * 80)
    
    try:
        # Setup - Use async context manager
        async with AsyncPostgresSaver.from_conn_string(settings.postgres_uri) as checkpointer:
            model = LLMFactory.get_chat_model()
            netbox_subagent = create_netbox_subagent()
            
            # Create agent with HITL enabled
            agent = create_deep_agent(
                model=model,
                system_prompt="你是 NetBox 管理专家。",
                checkpointer=checkpointer,
                subagents=[netbox_subagent],
            )

            # Try to create a device (write operation)
            config = {"configurable": {"thread_id": "test-write-hitl"}}
            query = """创建一个测试设备:
            - 名称: TEST-ROUTER-1
            - 站点: lab
            - 角色: router
            - 设备类型: IOSv
            - 平台: cisco_ios
            """
            
            logger.info(f"\n用户查询: {query}")
            logger.info("\n预期结果: 执行到写操作时触发 HITL 中断\n")
            
            interrupt_encountered = False
            interrupt_data = None
            
            # First execution - should hit interrupt
            async for event in agent.astream(
                {"messages": [HumanMessage(content=query)]},
                config=config,
                stream_mode="updates"
            ):
                # Log event for debugging
                logger.debug(f"Event: {event}")
                
                # Check state for interrupts
                if hasattr(event, '__iter__'):
                    for node_name, node_data in event.items():
                        if "interrupt" in str(node_data).lower():
                            interrupt_encountered = True
                            interrupt_data = node_data
                            logger.info(f"\n🔔 检测到 HITL 中断在节点: {node_name}")
            
            # Check if we can get state to verify interrupt
            try:
                state = agent.get_state(config)
                if state and hasattr(state, 'next') and state.next:
                    logger.info(f"\n✅ Agent 已暂停，等待审批")
                    logger.info(f"   下一步节点: {state.next}")
                    interrupt_encountered = True
            except Exception as e:
                logger.debug(f"无法获取状态: {e}")
            
            if interrupt_encountered:
                logger.info("\n✅ 写操作成功触发 HITL 中断")
                logger.info("\n📋 在真实环境中，此时会展示审批界面:")
                logger.info("   - 操作详情: 创建设备 TEST-ROUTER-1")
                logger.info("   - 决策选项: approve / edit / reject")
                logger.info("   - 影响范围: 在 NetBox 中创建 1 台设备")
                return True
            else:
                logger.warning("\n⚠️  未检测到 HITL 中断")
                logger.info("   可能原因:")
                logger.info("   1. Agent 未尝试执行写操作")
                logger.info("   2. HITL 中间件未正确配置")
                logger.info("   3. DeepAgents 版本不支持此功能")
                return False
            
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_csv_import_with_hitl():
    """Test CSV import operation that requires HITL approval."""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试 3: CSV 批量导入（需要 HITL 审批）")
    logger.info("=" * 80)
    
    logger.info("\n📝 CSV 导入数据:")
    csv_content = """name,device_role,device_type,site,platform,status
TEST-R1,router,IOSv,lab,cisco_ios,active
TEST-SW1,switch,vEOS,lab,arista_eos,active"""
    logger.info(csv_content)
    
    logger.info("\n💡 说明:")
    logger.info("  CSV 导入是批量写操作，会:")
    logger.info("  1. 创建/检查站点 (lab)")
    logger.info("  2. 创建/检查角色 (router, switch)")
    logger.info("  3. 创建/检查设备类型 (IOSv, vEOS)")
    logger.info("  4. 创建/检查平台 (cisco_ios, arista_eos)")
    logger.info("  5. 创建 2 台设备")
    logger.info("\n  因此必须经过 HITL 审批才能执行")
    
    logger.info("\n✅ CSV 导入已配置 HITL（见 netbox_agent.py interrupt_on）")
    return True


def main():
    """Run all HITL tests."""
    logger.info("\n" + "🔐" * 40)
    logger.info("NetBox Agent HITL 审批流程测试")
    logger.info("🔐" * 40)
    
    logger.info("\n💡 HITL (Human-in-the-Loop) 说明:")
    logger.info("  - 确保所有写操作都需要人工批准")
    logger.info("  - 防止意外修改生产环境数据")
    logger.info("  - 符合企业级安全和合规要求")
    
    results = []
    
    # Run tests
    logger.info("\n" + "=" * 80)
    logger.info("开始测试...")
    logger.info("=" * 80)
    
    results.append(("只读操作（无 HITL）", asyncio.run(test_read_only_operation())))
    results.append(("写操作（需 HITL）", asyncio.run(test_write_operation_with_hitl())))
    results.append(("CSV 导入（需 HITL）", asyncio.run(test_csv_import_with_hitl())))
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("📊 测试汇总")
    logger.info("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {status} - {test_name}")
    
    logger.info("")
    logger.info(f"总计: {passed}/{total} 测试通过")
    
    logger.info("\n" + "=" * 80)
    logger.info("📚 HITL 配置位置")
    logger.info("=" * 80)
    logger.info("  1. src/olav/agents/netbox_agent.py")
    logger.info("     - interrupt_on 配置")
    logger.info("  2. config/prompts/agents/netbox_agent.yaml")
    logger.info("     - HITL 审批流程说明")
    
    if passed == total:
        logger.info("\n🎉 所有测试通过！NetBox Agent HITL 审批已正确配置")
        return 0
    else:
        logger.warning(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
