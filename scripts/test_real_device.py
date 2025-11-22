"""
真实设备测试脚本 - OLAV 双 Agent 架构验证

用法:
  python scripts/test_real_device.py --device R1 --query "查询接口状态"
  python scripts/test_real_device.py --device R2 --query "查询 BGP 邻居" --verbose
  python scripts/test_real_device.py --list-devices  # 列出 NetBox 中的设备
  
场景:
  1. NETCONF 成功 (R1): 直接使用 NETCONF 查询
  2. NETCONF 失败 → CLI (R2): 自动降级到 CLI
  3. 纯 CLI (R3): 设备不支持 NETCONF
  4. HITL 审批: 配置操作触发人工审批
"""

import asyncio
import argparse
import logging
import os
import sys
from pathlib import Path

# 设置 PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

from deepagents import create_deep_agent
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver

from olav.core.llm import LLMFactory
from olav.core.prompt_manager import prompt_manager
from olav.agents.suzieq_agent import create_suzieq_subagent
from olav.agents.rag_agent import create_rag_subagent
from olav.agents.netconf_agent import create_netconf_subagent
from olav.agents.cli_agent import create_cli_subagent


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    return logging.getLogger(__name__)


async def verify_environment():
    """验证环境配置"""
    logger = logging.getLogger(__name__)
    
    logger.info("🔍 验证环境配置...")
    
    # 检查必需环境变量
    required_env = {
        "POSTGRES_URI": "PostgreSQL 连接字符串",
        "LLM_API_KEY": "LLM API Key (或 Ollama 不需要)",
        "LLM_PROVIDER": "LLM 提供商 (openai/ollama)",
        "NETBOX_URL": "NetBox URL",
        "NETBOX_TOKEN": "NetBox API Token"
    }
    
    missing = []
    for var, desc in required_env.items():
        value = os.getenv(var)
        if not value or value == "":
            missing.append(f"{var} ({desc})")
        else:
            # 隐藏敏感信息
            if "KEY" in var or "TOKEN" in var or "PASSWORD" in var:
                display_value = value[:10] + "..." if len(value) > 10 else "***"
            else:
                display_value = value
            logger.info(f"  ✓ {var}: {display_value}")
    
    if missing:
        logger.error("❌ 缺少环境变量:")
        for var in missing:
            logger.error(f"  - {var}")
        logger.info("\n请检查 .env 文件配置")
        return False
    
    # 检查 PostgreSQL 连接
    try:
        postgres_uri = os.getenv("POSTGRES_URI")
        logger.info(f"📡 测试 PostgreSQL 连接...")
        
        # 注意: PostgresSaver.from_conn_string 返回 context manager
        with PostgresSaver.from_conn_string(postgres_uri) as checkpointer:
            # 测试查询
            with checkpointer.conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
                logger.info(f"  ✓ PostgreSQL: {version.split(',')[0]}")
        
    except Exception as e:
        logger.error(f"❌ PostgreSQL 连接失败: {e}")
        logger.info("请检查:")
        logger.info("  1. PostgreSQL 容器运行: docker ps | grep postgres")
        logger.info("  2. 端口映射: 55432:5432")
        logger.info("  3. 初始化: docker-compose --profile init up olav-init")
        return False
    
    logger.info("✅ 环境验证通过")
    return True


async def list_netbox_devices():
    """列出 NetBox 中的设备"""
    logger = logging.getLogger(__name__)
    
    try:
        import requests
        
        netbox_url = os.getenv("NETBOX_URL")
        netbox_token = os.getenv("NETBOX_TOKEN")
        
        headers = {
            "Authorization": f"Token {netbox_token}",
            "Content-Type": "application/json"
        }
        
        logger.info("📋 从 NetBox 获取设备列表...")
        response = requests.get(
            f"{netbox_url}/api/dcim/devices/",
            headers=headers,
            params={"tag": "olav-managed"}
        )
        
        if response.status_code != 200:
            logger.error(f"❌ NetBox API 调用失败: {response.status_code}")
            logger.error(f"   响应: {response.text}")
            return []
        
        devices = response.json().get("results", [])
        
        if not devices:
            logger.warning("⚠️  未找到标记为 'olav-managed' 的设备")
            logger.info("请在 NetBox 中添加设备并打上 'olav-managed' 标签")
            return []
        
        logger.info(f"✓ 找到 {len(devices)} 个设备:\n")
        
        print("┌─────────┬──────────────┬─────────────────┬─────────────┬────────────┐")
        print("│ 名称    │ 平台         │ IP 地址         │ NETCONF     │ 状态       │")
        print("├─────────┼──────────────┼─────────────────┼─────────────┼────────────┤")
        
        for device in devices:
            name = device.get("name", "N/A")
            platform = device.get("platform", {}).get("name", "N/A") if device.get("platform") else "N/A"
            ip = device.get("primary_ip", {}).get("address", "N/A") if device.get("primary_ip") else "N/A"
            
            # 检查 custom fields 中的 NETCONF 支持
            custom_fields = device.get("custom_fields", {})
            supports_netconf = custom_fields.get("supports_netconf", "未知")
            netconf_status = "✅" if supports_netconf else "❌"
            
            status = device.get("status", {}).get("label", "N/A")
            
            print(f"│ {name:<7} │ {platform:<12} │ {ip:<15} │ {netconf_status:<11} │ {status:<10} │")
        
        print("└─────────┴──────────────┴─────────────────┴─────────────┴────────────┘")
        
        return devices
        
    except Exception as e:
        logger.error(f"❌ 获取设备列表失败: {e}")
        import traceback
        traceback.print_exc()
        return []


async def test_real_device(device: str, query: str, verbose: bool = False):
    """测试真实设备"""
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info(f"🎯 测试设备: {device}")
    logger.info(f"📋 查询: {query}")
    logger.info("=" * 80)
    
    # 验证环境
    if not await verify_environment():
        return False
    
    # 创建 SubAgents
    logger.info("\n📦 创建 SubAgents...")
    try:
        suzieq_subagent = create_suzieq_subagent()
        rag_subagent = create_rag_subagent()
        netconf_subagent = create_netconf_subagent()
        cli_subagent = create_cli_subagent()
        
        logger.info(f"  ✓ {suzieq_subagent['name']}")
        logger.info(f"  ✓ {rag_subagent['name']}")
        logger.info(f"  ✓ {netconf_subagent['name']}")
        logger.info(f"  ✓ {cli_subagent['name']}")
        
    except Exception as e:
        logger.error(f"❌ SubAgent 创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 创建 Root Agent
    logger.info("\n🤖 创建 Root Agent...")
    try:
        model = LLMFactory.get_chat_model()
        
        with PostgresSaver.from_conn_string(os.getenv("POSTGRES_URI")) as checkpointer:
            
            root_prompt = prompt_manager.load_agent_prompt(
                "root_agent",
                user_name="测试用户",
                network_context=f"测试设备: {device}"
            )
            
            # 追加降级策略
            fallback_strategy = """

## NETCONF → CLI 自动降级策略

**执行顺序**:
1. 优先尝试 **netconf-executor** (标准化、原子回滚)
2. 如果 NETCONF 返回错误包含 "connection failed" 或 "Connection refused":
   - 更新计划: "NETCONF 不可用，降级到 CLI 方案"
   - 调用 **cli-executor** 完成相同任务
3. 如果 CLI 也失败，向用户报告并请求指导
"""
            
            agent = create_deep_agent(
                model=model,
                system_prompt=root_prompt + fallback_strategy,
                checkpointer=checkpointer,
                subagents=[suzieq_subagent, rag_subagent, netconf_subagent, cli_subagent]
            )
            
            logger.info("  ✓ Root Agent 创建成功")
            logger.info(f"  - SubAgents: {len([suzieq_subagent, rag_subagent, netconf_subagent, cli_subagent])}")
            logger.info(f"  - LLM: {os.getenv('LLM_PROVIDER')} / {os.getenv('LLM_MODEL_NAME')}")
            
            # 执行测试
            logger.info("\n▶️  开始执行...")
            logger.info("-" * 80)
            
            test_message = HumanMessage(content=f"{query} (设备: {device})")
            config = {
                "configurable": {
                    "thread_id": f"test-{device}-{os.getpid()}"
                }
            }
            
            # 追踪工具调用
            tools_called = []
            netconf_failed = False
            cli_executed = False
            
            try:
                async for event in agent.astream_events(
                    {"messages": [test_message]},
                    config=config,
                    version="v2"
                ):
                    kind = event.get("event")
                    
                    if kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            print(chunk.content, end="", flush=True)
                    
                    elif kind == "on_tool_start":
                        tool_name = event.get("name")
                        tool_input = event.get("data", {}).get("input")
                        tools_called.append(tool_name)
                        logger.info(f"\n🔧 调用工具: {tool_name}")
                        if verbose:
                            logger.debug(f"   输入: {tool_input}")
                    
                    elif kind == "on_tool_end":
                        tool_name = event.get("name")
                        output = event.get("data", {}).get("output")
                        logger.info(f"✓ 工具完成: {tool_name}")
                        
                        # 检查 NETCONF 失败
                        if tool_name == "netconf_tool" and isinstance(output, dict):
                            if not output.get("success"):
                                netconf_failed = True
                                error = output.get("error", "Unknown error")
                                logger.warning(f"⚠️  NETCONF 失败: {error}")
                                
                                if "connection failed" in error.lower():
                                    logger.info("   → 预期将降级到 CLI Agent")
                        
                        # 检查 CLI 执行
                        elif tool_name == "cli_tool" and isinstance(output, dict):
                            if output.get("success"):
                                cli_executed = True
                                logger.info("✓ CLI 降级成功")
                                if output.get("parsed"):
                                    logger.info("✓ 输出已 TextFSM 解析为结构化数据")
                
                logger.info("\n" + "-" * 80)
                logger.info("✅ 执行完成")
                
                # 验证测试结果
                logger.info("\n📊 测试结果验证:")
                logger.info(f"  工具调用序列: {' → '.join(tools_called)}")
                
                if netconf_failed and cli_executed:
                    logger.info("  ✅ 降级流程正确:")
                    logger.info("     1. NETCONF 失败被检测")
                    logger.info("     2. CLI Agent 自动接管")
                    logger.info("     3. 返回结构化数据")
                elif "netconf_tool" in tools_called and not netconf_failed:
                    logger.info("  ✅ NETCONF 成功路径:")
                    logger.info("     1. NETCONF 直接成功")
                    logger.info("     2. 无需降级")
                elif "cli_tool" in tools_called and "netconf_tool" not in tools_called:
                    logger.info("  ℹ️  纯 CLI 路径:")
                    logger.info("     1. 直接使用 CLI")
                
                return True
                
            except KeyboardInterrupt:
                logger.warning("\n⚠️  用户中断执行")
                return False
            
            except Exception as e:
                logger.error(f"\n❌ 执行失败: {e}")
                import traceback
                traceback.print_exc()
                return False
        
    except Exception as e:
        logger.error(f"❌ Agent 创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="OLAV 真实设备测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 列出可用设备
  python scripts/test_real_device.py --list-devices
  
  # 测试 NETCONF 成功路径
  python scripts/test_real_device.py --device R1 --query "查询接口状态"
  
  # 测试 NETCONF → CLI 降级
  python scripts/test_real_device.py --device R2 --query "查询接口状态"
  
  # 测试 HITL 审批
  python scripts/test_real_device.py --device R1 --query "配置接口 GigabitEthernet0/0 的 MTU 为 9000"
  
  # 详细日志输出
  python scripts/test_real_device.py --device R1 --query "查询 BGP 邻居" --verbose
        """
    )
    
    parser.add_argument("--device", help="设备名称 (如: R1, R2, SW1)")
    parser.add_argument("--query", help="查询内容")
    parser.add_argument("--list-devices", action="store_true", help="列出 NetBox 中的设备")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志输出")
    
    args = parser.parse_args()
    
    # 设置日志
    logger = setup_logging(args.verbose)
    
    # 列出设备
    if args.list_devices:
        asyncio.run(list_netbox_devices())
        sys.exit(0)
    
    # 验证参数
    if not args.device or not args.query:
        parser.print_help()
        sys.exit(1)
    
    # 运行测试
    logger.info("\n🚀 OLAV 真实设备测试")
    success = asyncio.run(test_real_device(args.device, args.query, args.verbose))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
