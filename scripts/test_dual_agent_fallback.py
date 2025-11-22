"""
测试双 Agent 架构的基础组件

验证:
1. Prompt 文件是否正确加载
2. Agent 工厂函数是否可以创建 SubAgent
3. Tool 是否正确定义
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_prompt_loading():
    """测试 Prompt 文件加载"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 1: Prompt 文件加载")
    logger.info("=" * 80)
    
    try:
        from olav.core.prompt_manager import prompt_manager
        
        # 测试加载 NETCONF Prompt
        netconf_prompt = prompt_manager.load_agent_prompt("netconf_agent")
        logger.info(f"✓ NETCONF Prompt 加载成功")
        logger.info(f"  长度: {len(netconf_prompt)} 字符")
        logger.info(f"  预览: {netconf_prompt[:200]}...")
        
        # 测试加载 CLI Prompt  
        cli_prompt = prompt_manager.load_agent_prompt("cli_agent")
        logger.info(f"✓ CLI Prompt 加载成功")
        logger.info(f"  长度: {len(cli_prompt)} 字符")
        logger.info(f"  预览: {cli_prompt[:200]}...")
        
        return True
    except Exception as e:
        logger.error(f"✗ Prompt 加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_agent_factories():
    """测试 Agent 工厂函数"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 2: Agent 工厂函数")
    logger.info("=" * 80)
    
    try:
        # 测试 NETCONF Agent
        from olav.agents.netconf_agent import create_netconf_subagent
        netconf_agent = create_netconf_subagent()
        logger.info(f"✓ NETCONF SubAgent 创建成功")
        logger.info(f"  类型: {type(netconf_agent)}")
        logger.info(f"  名称: {netconf_agent['name']}")
        logger.info(f"  工具数量: {len(netconf_agent['tools'])}")
        logger.info(f"  工具: {[tool.name for tool in netconf_agent['tools']]}")
        
        # 测试 CLI Agent
        from olav.agents.cli_agent import create_cli_subagent
        cli_agent = create_cli_subagent()
        logger.info(f"✓ CLI SubAgent 创建成功")
        logger.info(f"  类型: {type(cli_agent)}")
        logger.info(f"  名称: {cli_agent['name']}")
        logger.info(f"  工具数量: {len(cli_agent['tools'])}")
        logger.info(f"  工具: {[tool.name for tool in cli_agent['tools']]}")
        
        return True
    except Exception as e:
        logger.error(f"✗ Agent 创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tools():
    """测试工具定义"""
    logger.info("\n" + "=" * 80)
    logger.info("测试 3: 工具定义")
    logger.info("=" * 80)
    
    try:
        from olav.tools.nornir_tool import netconf_tool, cli_tool
        
        logger.info(f"✓ netconf_tool 导入成功")
        logger.info(f"  函数: {netconf_tool}")
        logger.info(f"  文档: {netconf_tool.__doc__[:200] if netconf_tool.__doc__ else 'None'}...")
        
        logger.info(f"✓ cli_tool 导入成功")
        logger.info(f"  函数: {cli_tool}")
        logger.info(f"  文档: {cli_tool.__doc__[:200] if cli_tool.__doc__ else 'None'}...")
        
        return True
    except Exception as e:
        logger.error(f"✗ 工具导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    logger.info("\n" + "🧪 双 Agent 架构组件测试")
    
    results = []
    results.append(("Prompt 加载", test_prompt_loading()))
    results.append(("Agent 工厂", test_agent_factories()))
    results.append(("工具定义", test_tools()))
    
    # 总结
    logger.info("\n" + "=" * 80)
    logger.info("测试总结")
    logger.info("=" * 80)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{status}: {name}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    logger.info(f"\n通过率: {passed}/{total} ({passed * 100 // total}%)")
    
    if passed == total:
        logger.info("\n🎉 所有测试通过！")
    else:
        logger.info("\n❌ 部分测试失败，请检查错误信息")


if __name__ == "__main__":
    main()
