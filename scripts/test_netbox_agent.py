"""Test NetBox Agent functionality.

Tests:
1. Query NetBox devices
2. Import devices from CSV
3. NetBox API schema search
4. Direct API operations
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from olav.agents.netbox_agent import create_netbox_subagent
from olav.tools.netbox_inventory_tool import query_netbox_devices, import_devices_from_csv
from olav.tools.netbox_tool import netbox_schema_search, netbox_api_call

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_netbox_agent_creation():
    """Test NetBox SubAgent creation."""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试 1: NetBox SubAgent 创建")
    logger.info("=" * 80)
    
    try:
        netbox_subagent = create_netbox_subagent()
        logger.info(f"✅ NetBox SubAgent 创建成功")
        logger.info(f"  - 名称: {netbox_subagent['name']}")
        logger.info(f"  - 描述: {netbox_subagent['description']}")
        logger.info(f"  - 工具数量: {len(netbox_subagent['tools'])}")
        logger.info(f"  - 工具列表:")
        for tool in netbox_subagent['tools']:
            logger.info(f"    • {tool.name}: {tool.description[:60]}...")
        return True
    except Exception as e:
        logger.error(f"❌ NetBox SubAgent 创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_query_devices():
    """Test querying NetBox devices."""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试 2: 查询 NetBox 设备")
    logger.info("=" * 80)
    
    try:
        # Query all olav-managed devices
        result = await query_netbox_devices.ainvoke({})
        
        logger.info(f"✅ 设备查询成功")
        logger.info(f"  - 设备总数: {result['count']}")
        
        if result['count'] > 0:
            logger.info(f"  - 设备列表:")
            for device in result['devices'][:5]:  # Show first 5
                logger.info(f"    • {device['name']}")
                logger.info(f"      - 站点: {device.get('site', 'N/A')}")
                logger.info(f"      - 角色: {device.get('role', 'N/A')}")
                logger.info(f"      - 平台: {device.get('platform', 'N/A')}")
                logger.info(f"      - 状态: {device.get('status', 'N/A')}")
                logger.info(f"      - IP: {device.get('primary_ip', 'N/A')}")
        else:
            logger.warning("⚠️  未找到设备")
            logger.info("💡 请确认:")
            logger.info("  1. NetBox 中已添加设备")
            logger.info("  2. 设备已打上 'olav-managed' 标签")
        
        return True
    except Exception as e:
        logger.error(f"❌ 设备查询失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_schema_search():
    """Test NetBox schema search."""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试 3: NetBox Schema 搜索")
    logger.info("=" * 80)
    
    try:
        # Search for device-related endpoints
        results = netbox_schema_search.invoke({"query": "create a new device"})
        
        logger.info(f"✅ Schema 搜索成功")
        logger.info(f"  - 找到 {len(results)} 个相关端点:")
        
        for result in results[:3]:  # Show first 3
            logger.info(f"    • {result['method']} {result['path']}")
            logger.info(f"      - 描述: {result['summary']}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Schema 搜索失败: {e}")
        logger.info("💡 确认 OpenSearch 中存在 'netbox-schema' 索引")
        import traceback
        traceback.print_exc()
        return False


async def test_csv_import():
    """Test CSV import functionality."""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试 4: CSV 批量导入 (模拟)")
    logger.info("=" * 80)
    
    # Sample CSV data
    csv_data = """name,device_role,device_type,site,platform,status,ip_address
TEST-R1,router,IOSv,TestSite,cisco_ios,active,192.168.99.1/24
TEST-SW1,switch,vEOS,TestSite,arista_eos,active,192.168.99.2/24"""
    
    try:
        logger.info("📝 CSV 内容:")
        logger.info(csv_data)
        logger.info("\n⚠️  这是只读测试，不会实际导入到 NetBox")
        logger.info("    如需实际导入，请取消注释下方代码\n")
        
        # Uncomment to actually import:
        # result = await import_devices_from_csv(csv_data)
        # logger.info(f"✅ CSV 导入完成")
        # logger.info(f"  - 成功: {result['success']} 台")
        # logger.info(f"  - 失败: {result['failed']} 台")
        # if result['errors']:
        #     logger.warning(f"  - 错误:")
        #     for error in result['errors']:
        #         logger.warning(f"    • {error}")
        
        logger.info("✅ CSV 导入测试跳过（只读模式）")
        return True
        
    except Exception as e:
        logger.error(f"❌ CSV 导入测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_api_call():
    """Test direct NetBox API call."""
    logger.info("\n" + "=" * 80)
    logger.info("🧪 测试 5: NetBox API 直接调用")
    logger.info("=" * 80)
    
    try:
        # Get list of sites
        result = netbox_api_call.invoke({"path": "/dcim/sites/", "method": "GET"})
        
        if result.get("status") == "error":
            logger.error(f"❌ API 调用失败: {result.get('message')}")
            return False
        
        logger.info(f"✅ API 调用成功")
        logger.info(f"  - 站点总数: {result.get('count', 0)}")
        
        if result.get('count', 0) > 0:
            logger.info(f"  - 站点列表:")
            for site in result['results'][:3]:  # Show first 3
                logger.info(f"    • {site['name']} (slug: {site['slug']})")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ API 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    logger.info("\n" + "🚀" * 40)
    logger.info("NetBox Agent 功能测试套件")
    logger.info("🚀" * 40)
    
    results = []
    
    # Run tests
    results.append(("SubAgent 创建", await test_netbox_agent_creation()))
    results.append(("设备查询", await test_query_devices()))
    results.append(("Schema 搜索", await test_schema_search()))
    results.append(("CSV 导入", await test_csv_import()))
    results.append(("API 调用", await test_api_call()))
    
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
    
    if passed == total:
        logger.info("🎉 所有测试通过！")
        return 0
    else:
        logger.warning(f"⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
