#!/usr/bin/env python3
"""Test Funnel Debugging with a real network fault.

This script:
1. Modifies R2's GigabitEthernet1 subnet mask from /24 to /30
2. This will break BGP peering between R1 and R2 (subnet mismatch)
3. Runs Deep Dive funnel debugging to diagnose the issue
4. Verifies if it can identify the root cause

Usage:
    uv run python scripts/test_funnel_debug.py
"""

import asyncio
import sys
import selectors
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from olav.core.llm import LLMFactory
from olav.tools.suzieq_tool import SuzieQTool


async def modify_r2_interface():
    """Modify R2's interface to create subnet mismatch using NornirSandbox."""
    print("\n" + "=" * 60)
    print("STEP 1: Modifying R2 GigabitEthernet1 subnet mask")
    print("=" * 60)
    
    try:
        from nornir.core.filter import F
        from nornir_netmiko.tasks import netmiko_send_config
        from olav.execution.backends.nornir_sandbox import NornirSandbox
        
        # Use NornirSandbox which reads from NetBox
        sandbox = NornirSandbox()
        
        # Filter for R2
        r2 = sandbox.nr.filter(F(name="R2"))
        
        if not r2.inventory.hosts:
            print("ERROR: R2 not found in NetBox inventory")
            print("Please ensure R2 has the 'olav-managed' tag in NetBox")
            return False
        
        # Configuration to apply (change /24 to /30)
        config_commands = [
            "interface GigabitEthernet1",
            "ip address 10.1.12.2 255.255.255.252",  # /30 instead of /24
        ]
        
        print(f"Applying configuration to R2:")
        for cmd in config_commands:
            print(f"  {cmd}")
        
        result = r2.run(task=netmiko_send_config, config_commands=config_commands)
        
        for host, host_result in result.items():
            if host_result.failed:
                print(f"ERROR: Failed to configure {host}: {host_result.exception}")
                return False
            print(f"SUCCESS: {host} configured")
        
        return True
        
    except ImportError as e:
        print(f"WARNING: Nornir not fully configured: {e}")
        print("Proceeding with SuzieQ-only diagnosis...")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        print("Proceeding with SuzieQ-only diagnosis...")
        return False


async def run_deep_dive_diagnosis():
    """Run Deep Dive funnel debugging to diagnose the issue."""
    print("\n" + "=" * 60)
    print("STEP 2: Running Deep Dive Funnel Debugging")
    print("=" * 60)
    
    # Import here to avoid circular imports
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from olav.workflows.deep_dive import DeepDiveWorkflow
    from olav.core.settings import settings
    
    # User query simulating the problem report
    user_query = "R1 和 R2 之间的 BGP 邻居无法建立，请排查原因"
    
    print(f"\n问题描述: {user_query}")
    print("\n开始漏斗式诊断...")
    print("-" * 40)
    
    try:
        async with AsyncPostgresSaver.from_conn_string(
            settings.postgres_uri
        ) as checkpointer:
            await checkpointer.setup()
            
            # Create workflow
            workflow = DeepDiveWorkflow()
            graph = workflow.build_graph(checkpointer)
            
            # Run the workflow
            config = {
                "configurable": {
                    "thread_id": f"test_funnel_debug_{asyncio.get_event_loop().time()}"
                }
            }
            
            initial_state = {
                "messages": [HumanMessage(content=user_query)],
            }
            
            print("\n=== Workflow Execution ===\n")
            
            async for event in graph.astream(initial_state, config):
                for node_name, node_output in event.items():
                    print(f"\n--- Node: {node_name} ---")
                    
                    # Print topology analysis
                    if "topology" in node_output:
                        topo = node_output["topology"]
                        print(f"受影响设备: {topo.get('affected_devices', [])}")
                        print(f"故障范围: {topo.get('scope', 'unknown')}")
                    
                    # Print diagnosis plan
                    if "diagnosis_plan" in node_output:
                        plan = node_output["diagnosis_plan"]
                        print(f"诊断计划阶段数: {len(plan.get('phases', []))}")
                        for phase in plan.get("phases", []):
                            print(f"  - {phase['name']} ({phase['layer']}): {phase['tables']}")
                    
                    # Print findings
                    if "findings" in node_output and node_output["findings"]:
                        print("发现问题:")
                        for f in node_output["findings"]:
                            print(f"  ⚠️  {f}")
                    
                    # Print final message
                    if "messages" in node_output:
                        for msg in node_output["messages"]:
                            if hasattr(msg, "content"):
                                print(f"\n{msg.content[:1000]}...")
            
            print("\n" + "=" * 60)
            print("Deep Dive 诊断完成")
            print("=" * 60)
            
    except Exception as e:
        print(f"ERROR: Workflow failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Fall back to direct SuzieQ query for testing
        print("\n回退到直接 SuzieQ 查询...")
        await run_suzieq_diagnosis()


async def run_suzieq_diagnosis():
    """Direct SuzieQ diagnosis as fallback."""
    print("\n" + "=" * 60)
    print("FALLBACK: Direct SuzieQ Diagnosis")
    print("=" * 60)
    
    tool = SuzieQTool()
    
    # Check BGP status
    print("\n--- BGP 状态检查 ---")
    bgp_result = await tool.execute(
        table="bgp",
        method="get",
        hostname="R1",
    )
    print(f"BGP 邻居状态 (R1):\n{bgp_result.data}")
    
    bgp_result2 = await tool.execute(
        table="bgp",
        method="get",
        hostname="R2",
    )
    print(f"BGP 邻居状态 (R2):\n{bgp_result2.data}")
    
    # Check interface status
    print("\n--- 接口状态检查 ---")
    intf_result = await tool.execute(
        table="interfaces",
        method="get",
        hostname="R1",
    )
    # Filter for GigabitEthernet1
    gi1_data = [r for r in intf_result.data if "GigabitEthernet1" in str(r.get("ifname", ""))]
    print(f"R1 GigabitEthernet1:\n{gi1_data}")
    
    intf_result2 = await tool.execute(
        table="interfaces",
        method="get",
        hostname="R2",
    )
    gi1_data2 = [r for r in intf_result2.data if "GigabitEthernet1" in str(r.get("ifname", ""))]
    print(f"R2 GigabitEthernet1:\n{gi1_data2}")
    
    # Check routes
    print("\n--- 路由检查 ---")
    route_result = await tool.execute(
        table="routes",
        method="get",
        hostname="R1",
    )
    # Filter for 10.1.12.x routes
    r12_routes = [r for r in route_result.data if "10.1.12" in str(r.get("prefix", ""))]
    print(f"R1 10.1.12.x 路由:\n{r12_routes}")
    
    # Analyze results
    print("\n" + "=" * 60)
    print("诊断分析")
    print("=" * 60)
    
    # Prepare context for LLM
    context = f"""
## BGP 状态
R1 BGP: {bgp_result.data}
R2 BGP: {bgp_result2.data}

## 接口状态
R1 GigabitEthernet1: {gi1_data}
R2 GigabitEthernet1: {gi1_data2}

## 路由信息
R1 10.1.12.x routes: {r12_routes}
"""
    
    # Use LLM to analyze
    llm = LLMFactory.get_chat_model()
    
    analysis_prompt = f"""你是网络故障诊断专家。分析以下信息，找出 R1 和 R2 之间 BGP 无法建立的根本原因。

{context}

## 背景信息
- R2 的 GigabitEthernet1 原本配置为 10.1.12.2/24
- 现在被修改为 10.1.12.2/30
- R1 的配置仍然是 10.1.12.1/24

请分析根本原因并给出修复建议。"""
    
    response = await llm.ainvoke([{"role": "user", "content": analysis_prompt}])
    print(response.content)


async def restore_r2_interface():
    """Restore R2's original interface configuration."""
    print("\n" + "=" * 60)
    print("STEP 3: Restoring R2 GigabitEthernet1 original config")
    print("=" * 60)
    
    try:
        from nornir.core.filter import F
        from nornir_netmiko.tasks import netmiko_send_config
        from olav.execution.backends.nornir_sandbox import NornirSandbox
        
        sandbox = NornirSandbox()
        r2 = sandbox.nr.filter(F(name="R2"))
        
        if not r2.inventory.hosts:
            print("R2 not found, skipping restore")
            return
        
        # Restore original configuration
        config_commands = [
            "interface GigabitEthernet1",
            "ip address 10.1.12.2 255.255.255.0",  # Back to /24
        ]
        
        result = r2.run(task=netmiko_send_config, config_commands=config_commands)
        for host, host_result in result.items():
            if host_result.failed:
                print(f"ERROR: Failed to restore {host}")
            else:
                print(f"SUCCESS: {host} restored")
    except Exception as e:
        print(f"ERROR: {e}")


async def main():
    """Main test flow."""
    print("=" * 60)
    print("Funnel Debugging Test - Subnet Mismatch Fault")
    print("=" * 60)
    print("""
测试场景:
- 故障注入: 将 R2 GigabitEthernet1 从 /24 改为 /30
- 预期症状: R1-R2 BGP 邻居无法建立
- 预期诊断: 漏斗式排错应发现子网掩码不匹配

OSI 层分析:
- L1 (物理层): 接口应该是 UP
- L2 (数据链路层): 应该正常
- L3 (网络层): 子网掩码不匹配导致无法通信
- L4+ (传输层): BGP 无法建立 TCP 连接
""")
    
    try:
        # Step 1: Modify configuration (inject fault)
        modified = await modify_r2_interface()
        
        if modified:
            # Wait for changes to take effect
            print("\n等待 10 秒让配置生效...")
            await asyncio.sleep(10)
        
        # Step 2: Run Deep Dive diagnosis
        await run_deep_dive_diagnosis()
        
        # Step 3: Restore original configuration
        if modified:
            restore = input("\n是否恢复原始配置? (y/n): ")
            if restore.lower() == "y":
                await restore_r2_interface()
        
    except KeyboardInterrupt:
        print("\n测试中断")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Fix for Windows asyncio with psycopg
    if sys.platform == "win32":
        # Use SelectorEventLoop instead of ProactorEventLoop
        selector = selectors.SelectSelector()
        loop = asyncio.SelectorEventLoop(selector)
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main())
        finally:
            loop.close()
    else:
        asyncio.run(main())
