"""
Debug LLM Response Format

测试 OpenRouter/DeepSeek 返回的原始数据结构，特别是 invalid_tool_calls 的格式。
"""
import os
import json
import logging
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Define a simple tool for testing
@tool
def get_interface_state(device: str, interface_name: str = None) -> dict:
    """获取设备接口状态
    
    Args:
        device: 设备名称（如 R1, R2）
        interface_name: 接口名称，可选（如 GigabitEthernet1）
    
    Returns:
        接口状态信息
    """
    return {"device": device, "interface": interface_name, "status": "up"}


async def main():
    """Test LLM response format"""
    # Load settings
    from olav.core.settings import settings
    from olav.core.llm import LLMFactory
    
    logger.info(f"Testing LLM: {settings.llm_provider} / {settings.llm_model_name}")
    
    # Create LLM with tool binding using factory
    llm = LLMFactory.get_chat_model(temperature=0)
    
    llm_with_tools = llm.bind_tools([get_interface_state])
    
    # Test query
    messages = [
        SystemMessage(content="你是网络运维助手，使用提供的工具查询设备信息。"),
        HumanMessage(content="查询设备 R1 的接口状态")
    ]
    
    logger.info("Sending query to LLM...")
    response = await llm_with_tools.ainvoke(messages)
    
    logger.info("=" * 80)
    logger.info("RAW RESPONSE OBJECT:")
    logger.info(f"Type: {type(response)}")
    logger.info(f"Response: {response}")
    
    logger.info("=" * 80)
    logger.info("RESPONSE DICT:")
    response_dict = response.dict()
    logger.info(json.dumps(response_dict, indent=2, ensure_ascii=False))
    
    logger.info("=" * 80)
    logger.info("TOOL CALLS:")
    if hasattr(response, 'tool_calls'):
        logger.info(f"tool_calls: {response.tool_calls}")
        for i, tc in enumerate(response.tool_calls):
            logger.info(f"  [{i}] {tc}")
    
    logger.info("=" * 80)
    logger.info("INVALID TOOL CALLS:")
    if hasattr(response, 'invalid_tool_calls'):
        logger.info(f"invalid_tool_calls: {response.invalid_tool_calls}")
        for i, itc in enumerate(response.invalid_tool_calls):
            logger.info(f"  [{i}] {itc}")
            logger.info(f"      Type: {type(itc)}")
            logger.info(f"      Dict: {itc.dict() if hasattr(itc, 'dict') else itc}")
            if hasattr(itc, 'args'):
                logger.info(f"      args type: {type(itc.args)}")
                logger.info(f"      args value: {itc.args}")
    
    logger.info("=" * 80)
    logger.info("ADDITIONAL KWARGS:")
    if hasattr(response, 'additional_kwargs'):
        logger.info(json.dumps(response.additional_kwargs, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import asyncio
    
    # Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
