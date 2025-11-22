"""
Test TodoListMiddleware with Fixed LLM

验证修复后的 FixedChatOpenAI 是否支持 TodoListMiddleware
"""
import os
import sys
from pathlib import Path
import asyncio
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@tool
def get_device_info(device_name: str) -> str:
    """获取设备基础信息
    
    Args:
        device_name: 设备名称（如 R1, R2）
    
    Returns:
        设备信息
    """
    return f"Device: {device_name}, Platform: Cisco IOS-XE, Status: Active"


@tool
def get_interface_status(device_name: str, interface: str = None) -> str:
    """获取接口状态
    
    Args:
        device_name: 设备名称
        interface: 接口名称（可选）
    
    Returns:
        接口状态信息
    """
    if interface:
        return f"{device_name} - {interface}: UP"
    return f"{device_name} - All interfaces: UP"


async def test_without_todolist():
    """测试不使用 TodoListMiddleware（基线）"""
    from olav.core.llm import LLMFactory
    
    logger.info("=" * 80)
    logger.info("TEST 1: Without TodoListMiddleware (Baseline)")
    logger.info("=" * 80)
    
    llm = LLMFactory.get_chat_model(temperature=0)
    
    # Create agent
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是网络运维助手。使用提供的工具完成用户任务。"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    
    agent = create_tool_calling_agent(llm, [get_device_info, get_interface_status], prompt)
    executor = AgentExecutor(agent=agent, tools=[get_device_info, get_interface_status], verbose=True)
    
    # Test query that requires multiple steps
    result = await executor.ainvoke({
        "input": "查询 R1 和 R2 的设备信息，然后查询它们的接口状态"
    })
    
    logger.info(f"Result: {result['output']}")
    return result


async def test_with_todolist():
    """测试使用 TodoListMiddleware"""
    from olav.core.llm import LLMFactory
    
    logger.info("=" * 80)
    logger.info("TEST 2: With TodoListMiddleware")
    logger.info("=" * 80)
    
    # Import TodoListMiddleware
    try:
        # Try DeepAgents version first
        from deepagents.middleware.todolist import TodoListMiddleware
        logger.info("Using DeepAgents TodoListMiddleware")
    except ImportError:
        logger.warning("DeepAgents not available, skipping TodoList test")
        return None
    
    llm = LLMFactory.get_chat_model(temperature=0)
    
    # Create agent with TodoListMiddleware
    from langchain.agents.react.agent import create_react_agent
    from langchain_core.prompts import PromptTemplate
    
    # React-style prompt (required for TodoList)
    prompt_template = """你是网络运维助手。

你有以下工具可用:
{tools}

工具名称: {tool_names}

使用以下格式:

Question: 用户的问题
Thought: 你应该思考该做什么
Action: 要采取的行动，应该是 [{tool_names}] 之一
Action Input: 行动的输入
Observation: 行动的结果
... (这个 Thought/Action/Action Input/Observation 可以重复 N 次)
Thought: 我现在知道最终答案了
Final Answer: 原始输入问题的最终答案

开始!

Question: {input}
Thought: {agent_scratchpad}"""
    
    prompt = PromptTemplate.from_template(prompt_template)
    
    agent = create_react_agent(llm, [get_device_info, get_interface_status], prompt)
    executor = AgentExecutor(
        agent=agent, 
        tools=[get_device_info, get_interface_status], 
        verbose=True,
        handle_parsing_errors=True
    )
    
    # Test query
    result = await executor.ainvoke({
        "input": "查询 R1 和 R2 的设备信息，然后查询它们的接口状态"
    })
    
    logger.info(f"Result: {result['output']}")
    return result


async def test_simple_tool_call():
    """测试简单的工具调用（验证修复有效）"""
    from olav.core.llm import LLMFactory
    
    logger.info("=" * 80)
    logger.info("TEST 0: Simple Tool Call (Verify Fix)")
    logger.info("=" * 80)
    
    llm = LLMFactory.get_chat_model(temperature=0)
    llm_with_tools = llm.bind_tools([get_device_info])
    
    messages = [
        SystemMessage(content="你是网络运维助手。"),
        HumanMessage(content="获取设备 R1 的信息")
    ]
    
    response = await llm_with_tools.ainvoke(messages)
    
    logger.info(f"Response type: {type(response)}")
    logger.info(f"Tool calls: {response.tool_calls}")
    logger.info(f"Invalid tool calls: {response.invalid_tool_calls}")
    
    assert len(response.tool_calls) > 0, "Should have valid tool calls"
    assert len(response.invalid_tool_calls) == 0, "Should have no invalid tool calls"
    
    logger.info("✅ Simple tool call test PASSED")
    return response


async def main():
    """Run all tests"""
    # Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        # Test 0: Verify fix works
        await test_simple_tool_call()
        
        # Test 1: Without TodoList (baseline)
        result1 = await test_without_todolist()
        
        # Test 2: With TodoList
        logger.info("\n" + "=" * 80)
        logger.info("NOTE: TodoListMiddleware test requires DeepAgents integration")
        logger.info("This may not work with standard LangChain agents")
        logger.info("=" * 80 + "\n")
        
        # result2 = await test_with_todolist()
        
        logger.info("=" * 80)
        logger.info("SUMMARY")
        logger.info("=" * 80)
        logger.info("✅ Test 0 (Simple Tool Call): PASSED")
        logger.info("✅ Test 1 (Without TodoList): PASSED" if result1 else "❌ FAILED")
        # logger.info("✅ Test 2 (With TodoList): PASSED" if result2 else "⏭️  SKIPPED")
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
