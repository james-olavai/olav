#!/usr/bin/env python3
"""
Live NetBox Bidirectional Sync Test.

This script tests sync against a real NetBox instance and SuzieQ data.

Usage:
    # Set PYTHONPATH and run
    $env:PYTHONPATH="$PWD\src;$PWD"; uv run python scripts/test_sync_live.py
"""

import asyncio
import selectors
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))


async def check_prerequisites():
    """Check that NetBox and SuzieQ are accessible."""
    print("=" * 60)
    print("📋 前置条件检查")
    print("=" * 60)
    
    from olav.tools.netbox_tool import NetBoxAPITool
    
    # Check NetBox
    print("\n检查 NetBox 连接...")
    netbox = NetBoxAPITool()
    result = await netbox.execute(
        path="/api/status/",
        method="GET",
    )
    
    if result.error:
        print(f"❌ NetBox 连接失败: {result.error}")
        return False
    
    # Handle status response
    if isinstance(result.data, list) and len(result.data) > 0:
        status_data = result.data[0]
        if isinstance(status_data, dict):
            version = status_data.get('netbox-version', 'connected')
        else:
            version = 'connected'
    elif isinstance(result.data, dict):
        version = result.data.get('netbox-version', 'connected')
    else:
        version = 'connected'
    print(f"✅ NetBox 版本: {version}")
    
    # Check devices
    result = await netbox.execute(
        path="/api/dcim/devices/",
        method="GET",
        params={"tag": "olav-managed"},
    )
    
    if result.error:
        print(f"❌ 设备查询失败: {result.error}")
        return False
    
    # result.data is always a list due to adapter
    devices = []
    for d in result.data:
        if isinstance(d, dict) and "name" in d:
            devices.append(d["name"])
    
    print(f"✅ 找到 {len(devices)} 台 olav-managed 设备: {devices}")
    
    if not devices:
        print("⚠️  没有设备可测试，请先添加 olav-managed 标签的设备")
        return False
    
    # Check SuzieQ parquet data
    print("\n检查 SuzieQ 数据...")
    parquet_path = Path("data/suzieq-parquet")
    
    if not parquet_path.exists():
        print(f"⚠️  SuzieQ parquet 目录不存在: {parquet_path}")
        print("   将使用 mock 数据进行测试")
    else:
        # List tables
        tables = [d.name for d in parquet_path.iterdir() if d.is_dir()]
        print(f"✅ SuzieQ 表: {tables[:5]}..." if len(tables) > 5 else f"✅ SuzieQ 表: {tables}")
    
    return True, devices


async def test_interface_comparison(devices: list[str]):
    """Test interface comparison between SuzieQ and NetBox."""
    print("\n" + "=" * 60)
    print("🔌 Test 1: Interface Comparison")
    print("=" * 60)
    
    from olav.sync.diff_engine import DiffEngine
    from olav.sync.models import EntityType
    from olav.tools.netbox_tool import NetBoxAPITool
    
    netbox = NetBoxAPITool()
    engine = DiffEngine(netbox_tool=netbox)
    
    # Run comparison for first device only (faster)
    device = devices[0]
    print(f"\n对比 {device} 的接口...")
    
    report = await engine.compare_all(
        devices=[device],
        entity_types=[EntityType.INTERFACE],
    )
    
    print(f"\n📊 结果统计:")
    print(f"  总接口数: {report.total_entities}")
    print(f"  匹配: {report.matched}")
    print(f"  不匹配: {report.mismatched}")
    print(f"  网络有/NetBox无: {report.missing_in_netbox}")
    print(f"  NetBox有/网络无: {report.missing_in_network}")
    
    if report.diffs:
        print(f"\n📋 差异详情 (共 {len(report.diffs)} 项):")
        for i, diff in enumerate(report.diffs[:10], 1):  # Show first 10
            icon = "✅" if diff.auto_correctable else "🔒"
            print(f"  [{i}] {diff.field}")
            print(f"      网络: {diff.network_value}")
            print(f"      NetBox: {diff.netbox_value}")
            print(f"      自动修正: {icon}")
        
        if len(report.diffs) > 10:
            print(f"  ... 还有 {len(report.diffs) - 10} 项差异")
    
    return report


async def test_device_comparison(devices: list[str]):
    """Test device info comparison between SuzieQ and NetBox."""
    print("\n" + "=" * 60)
    print("🖥️  Test 2: Device Info Comparison")
    print("=" * 60)
    
    from olav.sync.diff_engine import DiffEngine
    from olav.sync.models import EntityType
    from olav.tools.netbox_tool import NetBoxAPITool
    
    netbox = NetBoxAPITool()
    engine = DiffEngine(netbox_tool=netbox)
    
    print(f"\n对比 {len(devices)} 台设备信息...")
    
    report = await engine.compare_all(
        devices=devices,
        entity_types=[EntityType.DEVICE],
    )
    
    print(f"\n📊 结果统计:")
    print(f"  设备数: {report.total_entities}")
    print(f"  匹配: {report.matched}")
    print(f"  不匹配: {report.mismatched}")
    
    for diff in report.diffs:
        icon = "✅" if diff.auto_correctable else "🔒"
        print(f"\n  设备: {diff.device}")
        print(f"  字段: {diff.field}")
        print(f"  网络值: {diff.network_value}")
        print(f"  NetBox值: {diff.netbox_value}")
        print(f"  自动修正: {icon}")
    
    return report


async def test_ip_comparison(devices: list[str]):
    """Test IP address comparison between SuzieQ and NetBox."""
    print("\n" + "=" * 60)
    print("🌐 Test 3: IP Address Comparison")
    print("=" * 60)
    
    from olav.sync.diff_engine import DiffEngine
    from olav.sync.models import EntityType
    from olav.tools.netbox_tool import NetBoxAPITool
    
    netbox = NetBoxAPITool()
    engine = DiffEngine(netbox_tool=netbox)
    
    print(f"\n对比 {len(devices)} 台设备的 IP 地址...")
    
    report = await engine.compare_all(
        devices=devices,
        entity_types=[EntityType.IP_ADDRESS],
    )
    
    print(f"\n📊 结果统计:")
    print(f"  IP地址数: {report.total_entities}")
    print(f"  匹配: {report.matched}")
    print(f"  不匹配: {report.mismatched}")
    print(f"  网络有/NetBox无: {report.missing_in_netbox}")
    print(f"  NetBox有/网络无: {report.missing_in_network}")
    
    if report.diffs:
        print(f"\n📋 差异详情:")
        for diff in report.diffs[:10]:
            print(f"  {diff.device}: {diff.network_value} vs {diff.netbox_value}")
    
    return report


async def test_full_comparison(devices: list[str]):
    """Run full comparison and generate report."""
    print("\n" + "=" * 60)
    print("📊 Test 4: Full Comparison Report")
    print("=" * 60)
    
    from olav.sync.diff_engine import DiffEngine
    from olav.tools.netbox_tool import NetBoxAPITool
    
    netbox = NetBoxAPITool()
    engine = DiffEngine(netbox_tool=netbox)
    
    print(f"\n运行完整对比 (所有设备, 所有实体类型)...")
    
    report = await engine.compare_all(devices=devices)
    
    # Generate markdown report
    md = report.to_markdown()
    
    # Save report
    report_dir = Path("data/inspection-reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"sync_report_{timestamp}.md"
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)
    
    print(f"\n📄 报告已保存: {report_path}")
    print("\n" + "-" * 40)
    print(md)
    
    return report


async def test_reconciler_dry_run(report):
    """Test reconciler in dry-run mode."""
    print("\n" + "=" * 60)
    print("🔧 Test 5: Reconciler Dry Run")
    print("=" * 60)
    
    if not report or not report.diffs:
        print("没有差异需要同步。")
        return
    
    from olav.sync.reconciler import NetBoxReconciler
    from olav.tools.netbox_tool import NetBoxAPITool
    
    netbox = NetBoxAPITool()
    reconciler = NetBoxReconciler(
        netbox_tool=netbox,
        dry_run=True,
    )
    
    print(f"\n模拟同步 {len(report.diffs)} 个差异...")
    
    results = await reconciler.reconcile(
        report,
        auto_correct=True,
        require_hitl=True,
    )
    
    # Print stats
    stats = reconciler.get_stats()
    print(f"\n📊 同步统计:")
    for action, count in stats.items():
        if count > 0:
            print(f"  {action}: {count}")
    
    print(f"\n📋 操作详情:")
    for result in results:
        status = "✅" if result.success else "❌"
        print(f"  {status} {result.action.value}: {result.message}")
    
    return results


async def test_auto_correct_mtu():
    """Test auto-correcting a specific MTU mismatch."""
    print("\n" + "=" * 60)
    print("🔄 Test 6: Auto-Correct MTU (Interactive)")
    print("=" * 60)
    
    from olav.sync.models import (
        DiffResult, DiffSeverity, DiffSource, 
        EntityType, ReconciliationReport
    )
    from olav.sync.reconciler import NetBoxReconciler
    from olav.tools.netbox_tool import NetBoxAPITool
    
    print("""
此测试将模拟自动修正 MTU 不匹配。

场景:
- 设备: R1
- 接口: GigabitEthernet0/1
- 网络 MTU: 1500
- NetBox MTU: 9000 (错误)
- 操作: 自动修正 NetBox 为 1500
""")
    
    # Create a sample diff
    report = ReconciliationReport(device_scope=["R1"])
    report.add_diff(DiffResult(
        entity_type=EntityType.INTERFACE,
        device="R1",
        field="GigabitEthernet0/1.mtu",
        network_value=1500,
        netbox_value=9000,
        severity=DiffSeverity.INFO,
        source=DiffSource.SUZIEQ,
        auto_correctable=True,
        netbox_id=1,  # Would need real ID
        netbox_endpoint="/api/dcim/interfaces/",
    ))
    
    netbox = NetBoxAPITool()
    reconciler = NetBoxReconciler(
        netbox_tool=netbox,
        dry_run=True,  # Safe - won't make real changes
    )
    
    results = await reconciler.reconcile(
        report,
        auto_correct=True,
    )
    
    for result in results:
        print(f"结果: {result.action.value}")
        print(f"消息: {result.message}")
        print(f"成功: {result.success}")


async def interactive_hitl_demo():
    """Demo the HITL approval workflow."""
    print("\n" + "=" * 60)
    print("👤 Test 7: HITL Approval Demo (Interactive)")
    print("=" * 60)
    
    from olav.sync.models import (
        DiffResult, DiffSeverity, DiffSource, EntityType
    )
    from olav.sync.rules.hitl_required import get_hitl_prompt
    
    print("""
此测试演示 HITL (Human-in-the-Loop) 审批流程。

当发现以下类型的差异时，需要人工审批:
- 接口启用/禁用状态
- IP 地址变更
- VLAN 分配
- 新实体创建
""")
    
    # Create sample HITL-required diffs
    diffs = [
        DiffResult(
            entity_type=EntityType.INTERFACE,
            device="SW2",
            field="Ethernet0/2.enabled",
            network_value=False,
            netbox_value=True,
            severity=DiffSeverity.WARNING,
            source=DiffSource.CLI,
            auto_correctable=False,
            additional_context={"reason": "Port is err-disabled due to BPDU Guard"},
        ),
        DiffResult(
            entity_type=EntityType.IP_ADDRESS,
            device="R1",
            field="existence",
            network_value="192.168.100.1/24",
            netbox_value="missing",
            severity=DiffSeverity.WARNING,
            source=DiffSource.SUZIEQ,
            auto_correctable=False,
            additional_context={"interface": "Loopback0"},
        ),
    ]
    
    for i, diff in enumerate(diffs, 1):
        print(f"\n--- 差异 {i} ---")
        prompt = get_hitl_prompt(diff)
        print(prompt)
        
        # In real workflow, this would trigger LangGraph interrupt
        print("\n[在实际工作流中，这里会触发 LangGraph interrupt 等待用户审批]")


async def main():
    """Main test flow."""
    print("=" * 60)
    print("🔄 NetBox 双向同步 - Live 测试")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Check prerequisites
        result = await check_prerequisites()
        if not result:
            print("\n❌ 前置条件检查失败")
            return
        
        _, devices = result
        
        # Run tests
        print("\n" + "=" * 60)
        print("开始测试...")
        print("=" * 60)
        
        # Test 1: Interface comparison
        await test_interface_comparison(devices)
        
        # Test 2: Device comparison
        await test_device_comparison(devices)
        
        # Test 3: IP comparison
        await test_ip_comparison(devices)
        
        # Test 4: Full comparison and report
        report = await test_full_comparison(devices)
        
        # Test 5: Reconciler dry run
        await test_reconciler_dry_run(report)
        
        # Test 6: Auto-correct demo
        await test_auto_correct_mtu()
        
        # Test 7: HITL demo
        await interactive_hitl_demo()
        
        print("\n" + "=" * 60)
        print("✅ 所有测试完成!")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\n测试中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Fix for Windows asyncio
    if sys.platform == "win32":
        selector = selectors.SelectSelector()
        loop = asyncio.SelectorEventLoop(selector)
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main())
        finally:
            loop.close()
    else:
        asyncio.run(main())
