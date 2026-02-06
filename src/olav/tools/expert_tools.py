"""Expert Agent Tools - 高级分析专用工具

为Expert Agent提供专业的诊断和分析工具:
1. analyze_topology - 拓扑分析和邻居关系识别
2. get_device_peers - 自动发现设备邻居（范围扩展）
3. expand_scope_by_role - 基于角色扩展设备范围
4. generate_diagnosis_report - 生成专业诊断报告
5. search_similar_cases - 检索历史相似案例

这些工具使Expert Agent能够进行:
- 拓扑感知分析
- 动态范围扩展
- 智能联合查询
- 根因定位
- 专业报告生成
"""

import json
import logging
from datetime import datetime
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def analyze_topology(
    device: str | None = None,
    topology_type: str = "lldp",
) -> str:
    """分析网络拓扑和设备关系

    从LLDP/BGP/OSPF邻居数据中提取拓扑关系，用于:
    - 识别设备的直连邻居
    - 构建网络拓扑图
    - 发现关键节点
    - 支持范围扩展决策

    Args:
        device: 指定设备名（可选，为空则分析全网拓扑）
        topology_type: 拓扑类型 (lldp/bgp/ospf)

    Returns:
        JSON格式的拓扑数据:
        {
            "nodes": [{"name": "R1", "role": "core"}, ...],
            "edges": [{"source": "R1", "target": "R2", "interface": "Gi0/0"}, ...],
            "critical_nodes": ["R1", "R2"]
        }
    """
    from olav.lib.data_gateway import query_database

    # 根据拓扑类型选择数据源
    if topology_type == "lldp":
        sql = """
        SELECT
            device as source,
            neighbor as target,
            local_interface,
            remote_interface,
            capability
        FROM v_lldp
        """
    elif topology_type == "bgp":
        sql = """
        SELECT
            device as source,
            neighbor as target,
            state,
            asn as remote_asn,
            uptime
        FROM v_bgp_neighbors
        """
    elif topology_type == "ospf":
        sql = """
        SELECT
            device as source,
            neighbor as target,
            state,
            router_id as remote_router_id
        FROM v_ospf_neighbors
        """
    else:
        return json.dumps({"error": f"Unknown topology type: {topology_type}"})

    # Execute query without WHERE clause (filter in Python to avoid SQL injection)
    # SQL injection fix: do not use f-string for device filter
    try:
        rows = query_database(sql)

        # query_database returns list[dict] directly, no unwrapping needed
        # Filter by device in Python layer (security fix - no SQL injection)
        if device:
            rows = [r for r in rows if r.get("source") == device or r.get("device") == device]

        # Extract nodes and edges
        nodes = set()
        edges = []

        for row in rows:
            source = row.get("source") or row.get("device")
            target = row.get("target") or row.get("neighbor")

            if source:
                nodes.add(source)
            if target:
                nodes.add(target)

            if source and target:
                edge = {
                    "source": source,
                    "target": target,
                }

                # 添加额外信息
                if "local_interface" in row:
                    edge["local_interface"] = row["local_interface"]
                if "remote_interface" in row:
                    edge["remote_interface"] = row["remote_interface"]
                if "state" in row:
                    edge["state"] = row["state"]

                edges.append(edge)

        # 识别关键节点（度数最高的节点）
        node_degrees = {}
        for edge in edges:
            node_degrees[edge["source"]] = node_degrees.get(edge["source"], 0) + 1
            node_degrees[edge["target"]] = node_degrees.get(edge["target"], 0) + 1

        critical_nodes = sorted(node_degrees.items(), key=lambda x: x[1], reverse=True)[:3]

        topology = {
            "topology_type": topology_type,
            "device_filter": device,
            "nodes": [{"name": n} for n in sorted(nodes)],
            "edges": edges,
            "critical_nodes": [n[0] for n in critical_nodes],
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "avg_degree": sum(node_degrees.values()) / len(node_degrees) if node_degrees else 0,
            },
        }

        return json.dumps(topology, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Topology analysis failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def get_device_peers(device: str, topology_type: str = "lldp") -> str:
    """获取设备的所有直连邻居（用于动态范围扩展）

    Args:
        device: 设备名
        topology_type: 拓扑类型 (lldp/bgp/ospf)

    Returns:
        JSON格式的邻居列表:
        {
            "device": "R1",
            "peers": ["R2", "SW1", "R3"],
            "peer_details": [
                {"peer": "R2", "interface": "Gi0/0", "state": "up"},
                ...
            ]
        }
    """
    topology_json = await analyze_topology.ainvoke(
        {"device": device, "topology_type": topology_type}
    )

    try:
        topology = json.loads(topology_json)

        if "error" in topology:
            return json.dumps({"error": topology["error"]})

        # 提取该设备的所有邻居
        peers = set()
        peer_details = []

        for edge in topology.get("edges", []):
            if edge["source"] == device:
                peer = edge["target"]
                peers.add(peer)
                peer_details.append(
                    {
                        "peer": peer,
                        "local_interface": edge.get("local_interface", "unknown"),
                        "remote_interface": edge.get("remote_interface", "unknown"),
                        "state": edge.get("state", "unknown"),
                    }
                )
            elif edge["target"] == device:
                peer = edge["source"]
                peers.add(peer)
                peer_details.append(
                    {
                        "peer": peer,
                        "local_interface": edge.get("remote_interface", "unknown"),
                        "remote_interface": edge.get("local_interface", "unknown"),
                        "state": edge.get("state", "unknown"),
                    }
                )

        result = {
            "device": device,
            "peers": sorted(peers),
            "peer_count": len(peers),
            "peer_details": peer_details,
        }

        return json.dumps(result, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Get device peers failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def expand_scope_by_role(device: str) -> str:
    """根据设备角色扩展范围（动态范围扩展）

    查询设备的角色属性，返回所有同角色设备，用于:
    - 从单设备问题扩展到设备组
    - 对比同角色设备配置
    - 检测组级问题

    Args:
        device: 参考设备名

    Returns:
        JSON格式的设备组:
        {
            "reference_device": "R1",
            "role": "core",
            "devices_in_role": ["R1", "R2", "R3", "R4"],
            "expansion_count": 4
        }
    """
    from olav.lib.data_gateway import query_database
    import re
    
    # SQL injection防护：设备名和角色名必须是合法的标识符
    if not re.match(r'^[a-zA-Z0-9_-]+$', device):
        return json.dumps({"error": f"Invalid device name: {device}. Must be alphanumeric with dash/underscore."})

    # 查询设备角色（使用query_database直接访问v_system）
    sql = f"""
    SELECT DISTINCT
        device,
        role,
        site,
        platform
    FROM v_system
    WHERE device = '{device}'
    """

    try:
        rows = query_database(sql)

        # query_database returns list[dict] directly
        if not rows:
            return json.dumps({"error": f"Device {device} not found in database"})

        device_info = rows[0]
        role = device_info.get("role", "unknown")
        
        # SQL injection防护：角色名校验
        if not re.match(r'^[a-zA-Z0-9_-]+$', role):
            return json.dumps({"error": f"Invalid role name in database: {role}"})

        # 查询所有同角色设备
        sql2 = f"""
        SELECT device, platform, site
        FROM v_system
        WHERE role = '{role}'
        ORDER BY device
        """

        result2_rows = query_database(sql2)

        # query_database returns list[dict] directly
        devices_in_role = [r.get("device") for r in result2_rows if r.get("device")]

        expansion = {
            "reference_device": device,
            "role": role,
            "site": device_info.get("site", "unknown"),
            "platform": device_info.get("platform", "unknown"),
            "devices_in_role": devices_in_role,
            "expansion_count": len(devices_in_role),
        }

        return json.dumps(expansion, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Expand scope by role failed: {e}")
        return json.dumps({"error": str(e)})


@tool
def generate_diagnosis_report(
    symptom: str,
    investigation_steps: list[str],
    root_cause: str,
    affected_devices: list[str],
    recommendations: list[str],
) -> str:
    """生成专业诊断报告（Markdown格式）

    Args:
        symptom: 问题症状描述
        investigation_steps: 调查步骤列表
        root_cause: 根本原因
        affected_devices: 受影响设备
        recommendations: 建议措施

    Returns:
        Markdown格式的诊断报告
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = f"""# 🔍 网络问题诊断报告

**生成时间**: {timestamp}
**症状**: {symptom}

---

## 📋 调查过程

"""

    for i, step in enumerate(investigation_steps, 1):
        report += f"{i}. {step}\n"

    report += f"""
---

## 🎯 根本原因

{root_cause}

---

## 🖥️ 受影响设备

"""

    for device in affected_devices:
        report += f"- {device}\n"

    report += """
---

## 💡 建议措施

"""

    for i, rec in enumerate(recommendations, 1):
        report += f"{i}. {rec}\n"

    report += """
---

## 📊 下一步行动

- [ ] 执行建议措施
- [ ] 验证问题解决
- [ ] 更新配置文档
- [ ] 监控相关指标

"""

    return report


@tool
async def search_similar_cases(
    symptom: str,
    skill_name: str = "network-expert",
    max_results: int = 5,
) -> str:
    """检索历史相似案例（Agentic Learning）

    从知识库中检索类似的历史诊断案例，用于:
    - 参考历史解决方案
    - 避免重复调查
    - 加速根因定位

    Args:
        symptom: 问题症状描述
        skill_name: 技能名称（用于过滤案例）
        max_results: 最大返回数量

    Returns:
        JSON格式的相似案例:
        [
            {
                "symptom": "R1 BGP邻居down",
                "root_cause": "接口MTU不匹配",
                "solution": "修改接口MTU为1500",
                "age_days": 7
            },
            ...
        ]
    """
    try:
        from olav.lib.data_gateway import get_gateway

        gw = get_gateway()

        # 提取关键词（简单实现）
        keywords = [w for w in symptom.split() if len(w) > 2][:5]

        cases = []
        for keyword in keywords:
            similar = gw.search_similar_cases(
                skill_name=skill_name, symptom=keyword, max_age_days=90, limit=max_results
            )
            cases.extend(similar)

        # 去重
        seen = set()
        unique_cases = []
        for case in cases:
            key = (case.get("symptom", ""), case.get("root_cause", ""))
            if key not in seen:
                seen.add(key)
                unique_cases.append(case)

        result = unique_cases[:max_results]
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)

    except Exception as e:
        logger.warning(f"Search similar cases failed: {e}")
        return json.dumps([])


@tool
async def execute_join_query(
    table1: str,
    table2: str,
    join_column: str,
    columns: list[str] | None = None,
) -> str:
    """执行联合查询（自动生成JOIN SQL）

    简化的联合查询接口，自动生成JOIN语句。
    
    **安全限制**: 不支持 WHERE 条件以防止 SQL 注入。如需过滤，请在 Python 层处理结果。

    Args:
        table1: 主表名（如 v_bgp_neighbors）
        table2: 关联表名（如 v_interfaces）
        join_column: 关联列（如 device）
        columns: 要选择的列（可选）

    Returns:
        查询结果（JSON格式）

    Example:
        execute_join_query(
            table1="v_bgp_neighbors",
            table2="v_interfaces",
            join_column="device",
            columns=["b.device", "b.neighbor", "b.state", "i.status"]
        )
    """
    from olav.lib.data_gateway import query_database
    import re
    
    # SQL injection防护：表名、列名必须是合法的SQL标识符
    def is_valid_sql_identifier(name: str) -> bool:
        """检查是否为合法的SQL标识符（表名/列名）"""
        return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))
    
    if not is_valid_sql_identifier(table1):
        return json.dumps({"error": f"Invalid table name: {table1}"})
    if not is_valid_sql_identifier(table2):
        return json.dumps({"error": f"Invalid table name: {table2}"})
    if not is_valid_sql_identifier(join_column):
        return json.dumps({"error": f"Invalid join column: {join_column}"})
    
    # 如果指定了列名，也需要校验
    if columns:
        for col in columns:
            # 允许 table.column 格式，提取列名部分
            col_name = col.split('.')[-1].strip()
            if not is_valid_sql_identifier(col_name):
                return json.dumps({"error": f"Invalid column name: {col}"})

    # 构建SELECT子句
    if columns:
        select_clause = ", ".join(columns)
    else:
        # 使用数字后缀避免别名冲突
        select_clause = "t1.*, t2.*"

    # 构建SQL - 使用固定别名 t1/t2 避免首字母冲突
    t1_alias = "t1"
    t2_alias = "t2"

    sql = f"""
    SELECT {select_clause}
    FROM {table1} {t1_alias}
    JOIN {table2} {t2_alias} ON {t1_alias}.{join_column} = {t2_alias}.{join_column}
    """

    logger.info(f"Generated JOIN query: {sql}")

    try:
        rows = query_database(sql)
        return json.dumps({"result": rows, "row_count": len(rows)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"JOIN query failed: {e}")
        return json.dumps({"error": str(e)})


@tool
async def compare_device_configs(
    devices: list[str],
    config_section: str | None = None,
) -> str:
    """对比多设备配置（用于发现配置差异）

    Args:
        devices: 设备列表（如 ["R1", "R2"]）
        config_section: 配置段（如 "router bgp"，可选）

    Returns:
        配置对比结果（Markdown格式）

    Example:
        compare_device_configs(["R1", "R2"], "router bgp")
    """
    from olav.tools.sync_tools import diff_configs

    comparisons = []

    # 两两对比（使用 diff_configs 对比同一设备的历史配置）
    # 注意：diff_configs 本身是对比单设备的不同时间点配置
    # 对于多设备配置对比，这里简化为对比各自的最新配置状态
    for i in range(len(devices) - 1):
        device1 = devices[i]
        device2 = devices[i + 1]

        try:
            # 获取两个设备各自的最新配置（作为对比基线）
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            # 对比 device1 的今天和昨天配置（检测变化）
            result1 = diff_configs.invoke(
                {
                    "device": device1,
                    "date1": yesterday,
                    "date2": today,
                }
            )
            
            # 对比 device2 的今天和昨天配置（检测变化）
            result2 = diff_configs.invoke(
                {
                    "device": device2,
                    "date1": yesterday,
                    "date2": today,
                }
            )

            comparisons.append(
                f"## {device1} Configuration Changes\n\n{result1}\n\n"
                f"## {device2} Configuration Changes\n\n{result2}\n"
            )

        except Exception as e:  # noqa: S110
            logger.debug(f"Config comparison failed for {device1} vs {device2}: {e}")
            comparisons.append(f"## {device1} vs {device2}\n\nConfiguration comparison failed: {e}\n")

    return "\n".join(comparisons) if comparisons else "Unable to compare configurations (data unavailable)"


# =============================================================================
# Expert Tools Bundle
# =============================================================================


def get_expert_tools() -> list[Any]:
    """获取Expert Agent完整工具集

    Returns:
        工具列表（包含基础工具+Expert专用工具）
    """
    from langchain_community.tools import DuckDuckGoSearchResults

    from olav.tools.network import list_devices, nornir_execute
    from olav.tools.react_query import (
        discover_data,
        inspect_file,
        query_database,
    )
    from olav.tools.sync_tools import diff_configs

    return [
        # 基础查询工具
        query_database,
        list_devices,
        # CLI执行
        nornir_execute,
        # 知识库和案例检索
        discover_data,  # .olav/knowledge/ 文件发现
        inspect_file,  # 文件内容检查
        # 联网搜索 (复用现有工具，不重复造轮子)
        DuckDuckGoSearchResults(max_results=5),  # Web search for external knowledge
        # 配置管理
        diff_configs,
        # Expert专用工具
        analyze_topology,
        get_device_peers,
        expand_scope_by_role,
        execute_join_query,
        compare_device_configs,
        generate_diagnosis_report,
        search_similar_cases,
    ]
