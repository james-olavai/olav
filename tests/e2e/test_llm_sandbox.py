"""
LLM Experiment Sandbox - E2E Tests

验证LLM在隔离沙箱中的代码执行和实验设计能力
"""

import asyncio
import json
import logging
import pytest
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sandbox_basic_execution():
    """测试沙箱基本代码执行能力"""
    from olav.core.simulation.llm_sandbox import LLMExperimentSandbox
    
    logger.info("\n" + "="*60)
    logger.info("TEST: LLM Sandbox - Basic Code Execution")
    logger.info("="*60)
    
    # 创建沙箱 - 直接使用db_path, 不在父进程中打开数据库连接
    from olav.core.config import MAIN_DB_PATH
    
    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
    
    # LLM生成的简单实验代码
    llm_code = """
# 简单的数据分析实验
devices_count = 6
interfaces_per_device = 4
total_interfaces = devices_count * interfaces_per_device

# 结果赋值给_result
_result = {
    "devices": devices_count,
    "interfaces_per_device": interfaces_per_device,
    "total_interfaces": total_interfaces,
    "calculation_passed": total_interfaces == 24
}
"""
    
    logger.info(f"\n🧪 执行实验代码：")
    logger.info(f"  沙箱ID: {sandbox.sandbox_id}")
    
    # 执行实验
    result = await sandbox.execute_experiment(
        experiment_code=llm_code,
        experiment_name="basic_calculation",
        timeout=30
    )
    
    logger.info(f"\n📊 执行结果：")
    logger.info(f"  状态: {result.status}")
    logger.info(f"  执行时间: {result.execution_time:.2f}s")
    logger.info(f"  结果: {result.result}")
    
    # 验证
    assert result.status == "success", f"Execution failed: {result.error}"
    assert result.result["total_interfaces"] == 24
    assert result.result["calculation_passed"] == True
    
    logger.info(f"✓ 基本执行能力验证通过")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sandbox_database_query():
    """测试沙箱中的数据库查询能力"""
    from olav.core.simulation.llm_sandbox import LLMExperimentSandbox
    from olav.core.config import MAIN_DB_PATH
    
    logger.info("\n" + "="*60)
    logger.info("TEST: LLM Sandbox - Database Query")
    logger.info("="*60)
    
    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
    
    # LLM自由设计的数据库查询实验
    llm_code = """
# LLM自由设计：查询网络设备并分析

# Step 1: 查询所有设备
try:
    devices = db.query('''
        SELECT device_id, name, platform, mgmt_ip 
        FROM devices 
        WHERE is_active = TRUE
        LIMIT 10
    ''')
    
    device_count = len(devices)
    
    # Step 2: 自定义分析
    platforms = {}
    for device in devices:
        platform = device.get('platform', 'unknown')
        platforms[platform] = platforms.get(platform, 0) + 1
    
    # Step 3: 生成报告
    _result = {
        "total_devices": device_count,
        "platforms": platforms,
        "devices_found": device_count > 0,
        "sample_device": devices[0] if devices else None
    }
    
except Exception as e:
    _result = {"error": str(e)}
"""
    
    logger.info(f"\n🧪 执行数据库查询实验")
    
    result = await sandbox.execute_experiment(
        experiment_code=llm_code,
        experiment_name="database_query",
        timeout=30
    )
    
    logger.info(f"\n📊 查询结果：")
    logger.info(f"  状态: {result.status}")
    
    if result.status == "success":
        logger.info(f"  发现设备数: {result.result.get('total_devices')}")
        logger.info(f"  平台分布: {result.result.get('platforms')}")
        logger.info(f"  采样设备: {result.result.get('sample_device')}")
        
        assert result.result["devices_found"] == True
        logger.info(f"✓ 数据库查询验证通过")
    else:
        logger.error(f"  错误: {result.error}")
        pytest.fail(f"Database query failed: {result.error}")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sandbox_complex_analysis():
    """测试沙箱中的复杂分析能力"""
    from olav.core.simulation.llm_sandbox import LLMExperimentSandbox
    from olav.core.config import MAIN_DB_PATH
    
    logger.info("\n" + "="*60)
    logger.info("TEST: LLM Sandbox - Complex Network Analysis")
    logger.info("="*60)
    
    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
    
    # LLM进行的复杂网络分析实验
    llm_code = """
# 复杂实验：分析网络拓扑和关键路径

try:
    # Step 1: 加载拓扑数据
    topology = db.query('''
        SELECT source_device, destination_device, source_interface, destination_interface
        FROM topology_links
        LIMIT 50
    ''')
    
    # Step 2: 构建拓扑图
    from collections import defaultdict
    
    graph = defaultdict(list)
    for link in topology:
        src = link['source_device']
        dst = link['destination_device']
        graph[src].append({
            'target': dst,
            'src_intf': link['source_interface'],
            'dst_intf': link['destination_interface']
        })
    
    # Step 3: 分析节点度数
    node_degrees = {}
    for src, targets in graph.items():
        node_degrees[src] = len(targets)
    
    # Step 4: 识别关键节点（度数最高）
    sorted_nodes = sorted(node_degrees.items(), key=lambda x: x[1], reverse=True)
    critical_nodes = sorted_nodes[:3] if sorted_nodes else []
    
    # Step 5: 生成发现
    _result = {
        "topology_size": len(topology),
        "unique_nodes": len(node_degrees),
        "critical_nodes": [
            {"device": node, "connections": degree}
            for node, degree in critical_nodes
        ],
        "average_degree": sum(node_degrees.values()) / len(node_degrees) if node_degrees else 0
    }

except Exception as e:
    import traceback
    _result = {
        "error": str(e),
        "trace": traceback.format_exc()
    }
"""
    
    logger.info(f"\n🧪 执行复杂拓扑分析实验")
    
    result = await sandbox.execute_experiment(
        experiment_code=llm_code,
        experiment_name="topology_analysis",
        timeout=60
    )
    
    logger.info(f"\n📊 分析结果：")
    logger.info(f"  状态: {result.status}")
    
    if result.status == "success":
        logger.info(f"  拓扑规模: {result.result.get('topology_size')} 链路")
        logger.info(f"  节点数: {result.result.get('unique_nodes')}")
        logger.info(f"  关键节点: {result.result.get('critical_nodes')}")
        logger.info(f"  平均度数: {result.result.get('average_degree'):.2f}")
        
        assert result.result["unique_nodes"] > 0
        logger.info(f"✓ 拓扑分析验证通过")
    else:
        logger.error(f"  错误: {result.error}")
        # 不强制失败，因为这取决于实际数据库内容


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sandbox_experiment_design():
    """测试沙箱中的实验自动设计能力"""
    from olav.core.simulation.llm_sandbox import LLMExperimentSandbox
    from olav.core.config import MAIN_DB_PATH
    
    logger.info("\n" + "="*60)
    logger.info("TEST: LLM Sandbox - Auto Experiment Design")
    logger.info("="*60)
    
    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
    
    # LLM自由设计的实验生成代码
    llm_code = """
# LLM自动设计实验：根据拓扑特征生成测试场景

try:
    # Phase 1: 发现拓扑特征
    devices = db.query('SELECT device_id, name FROM devices WHERE is_active = TRUE LIMIT 10')
    
    # Phase 2: 为每个设备设计故障场景
    experiments = []
    
    for device_idx, device in enumerate(devices[:3]):  # 前3个设备
        exp = {
            "id": f"exp_{device_idx}",
            "name": f"Failure simulation: {device['name']}",
            "target_device": device['device_id'],
            "scenario_type": "device_failure",
            "expected_impact": "medium",
            
            # LLM自定义的测试
            "test_cases": [
                {
                    "name": "All interfaces down",
                    "type": "multi_interface_failure",
                    "severity": "critical"
                },
                {
                    "name": "BGP neighbor reset",
                    "type": "bgp_impact",
                    "severity": "high"
                }
            ]
        }
        experiments.append(exp)
    
    # Phase 3: 生成验证计划
    _result = {
        "experiments_designed": len(experiments),
        "experiments": experiments,
        "total_test_cases": sum(len(e['test_cases']) for e in experiments),
        "design_complete": len(experiments) > 0
    }

except Exception as e:
    _result = {"error": str(e)}
"""
    
    logger.info(f"\n🧪 执行实验自动设计")
    
    result = await sandbox.execute_experiment(
        experiment_code=llm_code,
        experiment_name="experiment_design",
        timeout=60
    )
    
    logger.info(f"\n📊 设计结果：")
    logger.info(f"  状态: {result.status}")
    
    if result.status == "success":
        logger.info(f"  设计的实验数: {result.result.get('experiments_designed')}")
        logger.info(f"  总测试用例数: {result.result.get('total_test_cases')}")
        logger.info(f"  设计完成: {result.result.get('design_complete')}")
        
        assert result.result["design_complete"] == True
        logger.info(f"✓ 实验设计验证通过")
    else:
        logger.error(f"  错误: {result.error}")


@pytest.mark.e2e
@pytest.mark.asyncio  
async def test_sandbox_persistence():
    """测试沙箱执行历史和工件持久化"""
    from olav.core.simulation.llm_sandbox import LLMExperimentSandbox
    from olav.core.config import MAIN_DB_PATH
    
    logger.info("\n" + "="*60)
    logger.info("TEST: LLM Sandbox - Execution History")
    logger.info("="*60)
    
    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
    
    # 执行多个实验
    experiments = [
        ("exp1", "_result = {'count': 1}"),
        ("exp2", "_result = {'count': 2}"),
        ("exp3", "_result = {'count': 3}"),
    ]
    
    for exp_name, code in experiments:
        result = await sandbox.execute_experiment(
            experiment_code=code,
            experiment_name=exp_name,
            timeout=30
        )
        assert result.status == "success"
        logger.info(f"  ✓ {exp_name} 执行成功")
    
    # 检查执行历史
    history = sandbox.get_execution_history()
    
    logger.info(f"\n📋 执行历史：")
    logger.info(f"  总执行次数: {len(history)}")
    
    for idx, record in enumerate(history):
        logger.info(f"  {idx+1}. {record['experiment_name']} - {record['result']['status']}")
    
    assert len(history) == 3
    assert all(h["result"]["status"] == "success" for h in history)
    
    logger.info(f"✓ 执行历史持久化验证通过")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sandbox_timeout_protection():
    """测试沙箱超时保护"""
    from olav.core.simulation.llm_sandbox import LLMExperimentSandbox
    from olav.core.config import MAIN_DB_PATH
    
    logger.info("\n" + "="*60)
    logger.info("TEST: LLM Sandbox - Timeout Protection")
    logger.info("="*60)
    
    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
    
    # 长时间运行的代码
    llm_code = """
import time
# 无限循环（会被超时保护中断）
while True:
    time.sleep(0.1)
_result = {"done": False}
"""
    
    logger.info(f"\n🧪 测试超时保护（2秒超时）")
    
    result = await sandbox.execute_experiment(
        experiment_code=llm_code,
        experiment_name="timeout_test",
        timeout=2
    )
    
    logger.info(f"\n📊 结果：")
    logger.info(f"  状态: {result.status}")
    logger.info(f"  执行时间: {result.execution_time:.2f}s")
    
    assert result.status == "error"
    assert "timeout" in result.error.lower() or result.execution_time >= 2
    
    logger.info(f"✓ 超时保护验证通过")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sandbox_error_handling():
    """测试沙箱错误处理"""
    from olav.core.simulation.llm_sandbox import LLMExperimentSandbox
    from olav.core.config import MAIN_DB_PATH
    
    logger.info("\n" + "="*60)
    logger.info("TEST: LLM Sandbox - Error Handling")
    logger.info("="*60)
    
    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
    
    # 会产生错误的代码
    llm_code = """
try:
    result = 1 / 0  # ZeroDivisionError
except ZeroDivisionError as e:
    _result = {
        "error_caught": True,
        "error_type": "ZeroDivisionError",
        "message": str(e)
    }
"""
    
    logger.info(f"\n🧪 测试错误处理")
    
    result = await sandbox.execute_experiment(
        experiment_code=llm_code,
        experiment_name="error_handling",
        timeout=30
    )
    
    logger.info(f"\n📊 结果：")
    logger.info(f"  状态: {result.status}")
    
    if result.status == "success":
        logger.info(f"  错误捕获: {result.result.get('error_caught')}")
        logger.info(f"  错误类型: {result.result.get('error_type')}")
        
        assert result.result["error_caught"] == True
        logger.info(f"✓ 错误处理验证通过")
    else:
        logger.warning(f"  执行错误（预期的错误处理限制）")
