"""Test NTC Schema ETL and discover_commands tool."""

import asyncio
import logging

from olav.etl.ntc_schema_etl import NTCSchemaETL
from olav.tools.ntc_tool import discover_commands, list_supported_platforms

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_ntc_schema_workflow():
    """Test complete NTC Schema ETL → discover_commands flow."""
    
    logger.info("=" * 60)
    logger.info("Step 1: Run NTC Schema ETL")
    logger.info("=" * 60)
    
    async with NTCSchemaETL() as etl:
        await etl.run()
    
    logger.info("\n" + "=" * 60)
    logger.info("Step 2: List supported platforms")
    logger.info("=" * 60)
    
    platforms_result = await list_supported_platforms()
    logger.info(f"Total platforms: {platforms_result.get('total_platforms')}")
    
    for platform in platforms_result.get("platforms", [])[:5]:
        logger.info(
            f"  - {platform['platform']}: {platform['template_count']} templates, "
            f"categories: {', '.join(platform['categories'][:3])}"
        )
    
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: Test discover_commands")
    logger.info("=" * 60)
    
    test_cases = [
        ("cisco_ios", "查看接口状态"),
        ("cisco_nxos", "查看BGP邻居"),
        ("juniper_junos", "查看路由表"),
        ("arista_eos", "查看LLDP邻居"),
        ("huawei_vrp", "查看设备版本"),
    ]
    
    for platform, intent in test_cases:
        result = await discover_commands(platform=platform, intent=intent)
        
        logger.info(f"\n Platform: {platform}, Intent: {intent}")
        logger.info(f" Fallback needed: {result.get('fallback_needed')}")
        
        commands = result.get("commands", [])
        if commands:
            top_cmd = commands[0]
            logger.info(f" ✓ Top match: {top_cmd['command']}")
            logger.info(f"   Category: {top_cmd['category']}")
            logger.info(f"   Has TextFSM: {top_cmd['has_textfsm']}")
            logger.info(f"   Confidence: {top_cmd['confidence']:.2f}")
        else:
            logger.warning(f" ✗ No templates found")
    
    logger.info("\n" + "=" * 60)
    logger.info("Schema-Aware CLI workflow test completed")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_ntc_schema_workflow())
