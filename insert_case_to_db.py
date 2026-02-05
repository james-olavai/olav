#!/usr/bin/env python3
"""把实战测试案例插入到skill.duckdb的history_cases表"""

import json
from pathlib import Path
from datetime import datetime
import duckdb
import uuid

# 新的案例数据
new_case = {
    "symptom": "OSPF邻居关系down，IP修改后子网不匹配",
    "devices_checked": ["R1", "R3"],
    "commands_used": [
        "show ip ospf neighbor",
        "show ip interface brief",
        "show running-config interface ethernet0/0"
    ],
    "diagnosis_steps": """
    1. 检查R3 OSPF邻居状态 → 无邻居 (异常)
    2. 检查R1 OSPF邻居状态 → R3消失，只有R2 (异常)
    3. 检查接口配置 → R3: 10.1.13.5/30, R1: 10.1.13.1/24
    4. 分析子网 → 10.1.13.5/30属于10.1.13.4/30，10.1.13.1/24属于10.1.13.0/24
    5. 根因确认 → 子网不匹配导致OSPF邻接失败
    """,
    "root_cause": "接口IP地址修改后，R3与R1不在同一子网，OSPF要求邻接设备在同一子网",
    "solution": """
    方案1 (推荐): 修改R3为/24子网
      config t
      int e0/0
      ip address 10.1.13.5 255.255.255.0
      
    方案2: 修改为共同的/30子网
      config t
      int e0/0
      ip address 10.1.13.2 255.255.255.252
      
    关键点: /30子网分块 (.0-.3, .4-.7, .8-.11...)
            10.1.13.5/30的子网是10.1.13.4/30 (.4-.7)
            10.1.13.1/24的子网是10.1.13.0/24 (.0-.255)
            不在同一子网 → OSPF失败
    """,
}

def insert_case():
    """插入案例到数据库"""
    
    db_path = Path(".olav/skills/network-analysis/skill.duckdb")
    print(f"📝 正在向数据库插入案例...")
    print(f"数据库: {db_path}")
    print()
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return False
    
    try:
        conn = duckdb.connect(str(db_path))
        
        # 插入新案例
        case_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO history_cases (
                id, symptom, devices_checked, commands_used, 
                diagnosis_steps, root_cause, solution, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                case_id,
                new_case["symptom"],
                json.dumps(new_case["devices_checked"], ensure_ascii=False),
                json.dumps(new_case["commands_used"], ensure_ascii=False),
                new_case["diagnosis_steps"],
                new_case["root_cause"],
                new_case["solution"],
                datetime.now(),
            ]
        )
        
        conn.close()
        
        print("✅ 案例插入成功！")
        print(f"\n📊 案例信息:")
        print(f"  症状: {new_case['symptom']}")
        print(f"  根因: {new_case['root_cause']}")
        print(f"  设备: {new_case['devices_checked']}")
        print(f"  命令: {len(new_case['commands_used'])}个")
        
        return True
        
    except Exception as e:
        print(f"❌ 插入失败: {e}")
        return False

if __name__ == "__main__":
    success = insert_case()
    
    if success:
        # 验证插入
        print("\n" + "=" * 100)
        print("📋 验证: 查询数据库中的所有案例")
        print("=" * 100)
        
        db_path = Path(".olav/skills/network-analysis/skill.duckdb")
        conn = duckdb.connect(str(db_path), read_only=True)
        
        cases = conn.execute(
            "SELECT symptom, root_cause, created_at FROM history_cases ORDER BY created_at DESC"
        ).fetchall()
        
        print(f"\n数据库中共有 {len(cases)} 个案例:")
        for i, case in enumerate(cases, 1):
            print(f"\n【案例 {i}】")
            print(f"  症状: {case[0]}")
            print(f"  根因: {case[1]}")
            print(f"  时间: {case[2]}")
        
        conn.close()
