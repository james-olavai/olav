# OLAV 数据库与目录架构设计 (v0.9.0)

> **版本**: v0.9.0  
> **创建日期**: 2026-02-01  
> **状态**: 架构重构方案  
> **目标**: 符合 Claude Code 规范、支持跨平台迁移、便于 API 访问

---

## 📋 设计原则

### 1. Skill 完全自包含
- **每个 Skill 独立目录**，包含 SKILL.md、scripts/、私有数据库
- **可独立打包迁移**：`cp -r .olav/skills/network-query .claude/skills/`

### 2. 数据分层隔离
- **私有数据** → Skill 目录内 (`skills/*/cache.duckdb`)
- **共享数据** → 统一 db/ 目录 (`db/snapshots.duckdb`)

### 3. 平台无关接口
- **统一 Data Gateway** → 抽象数据访问层
- **支持多平台**：CLI、Web API、Claude Code、Gemini Agent

---

## 🏗️ 新架构设计

### 目录结构

```
.olav/                         # 或 .claude/ 或 .gemini/ (平台无关)
│
├── skills/                    # ✅ Skill 自包含层
│   ├── network-query/
│   │   ├── SKILL.md           # 工具声明
│   │   ├── scripts/           # ✅ Skill 内部 scripts (符合 Claude Code)
│   │   │   ├── query_database.py
│   │   │   └── inspect_schema.py
│   │   └── skill.duckdb       # ✅ 学习数据库 (单文件多表)
│   │       ├── user_aliases        # 表: 别名映射
│   │       ├── query_templates     # 表: 查询模板
│   │       └── intent_cache        # 表: Intent Cache
│   │
│   ├── network-expert/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   ├── analyze_topology.py
│   │   │   ├── diagnose_issue.py
│   │   │   └── compare_snapshots.py
│   │   └── skill.duckdb       # ✅ 学习数据库 (单文件多表)
│   │       └── history_cases       # 表: 诊断案例库
│   │
│   ├── network-inspector/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   ├── inspect_device.py
│   │   │   └── generate_report.py
│   │   └── skill.duckdb       # ✅ 学习数据库 (单文件多表)
│   │       ├── inspection_tasks    # 表: 巡检任务
│   │       └── anomaly_patterns    # 表: 异常模式
│   │
│   ├── netbox-integration/    # 🔮 未来扩展
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   ├── sync_netbox.py
│   │   │   └── query_ipam.py
│   │   └── skill.duckdb       # 同步状态
│   │
│   └── textfsm-learning/      # 🔮 未来扩展
│       ├── SKILL.md
│       ├── scripts/
│       │   ├── learn_template.py
│       │   └── validate_template.py
│       └── skill.duckdb       # 学习的模板库
│
├── db/                        # ✅ 共享数据层
│   ├── snapshots.duckdb       # 全局网络快照 (所有 Skill 只读)
│   ├── topology.duckdb        # 拓扑数据 (所有 Skill 只读)
│   └── audit_logs.duckdb      # 命令审计日志 (所有 Skill 写入)
│
├── lib/                       # ✅ 平台无关工具库
│   ├── data_gateway.py        # 统一数据访问接口 (核心)
│   ├── database_utils.py      # DuckDB 连接池、错误处理
│   ├── parsing_utils.py       # 通用解析逻辑
│   └── skill_utils.py         # Skill 加载辅助
│
├── knowledge/                 # 知识库 (Markdown)
│   ├── aliases.md
│   ├── command-templates.md
│   └── solutions/
│
└── config/                    # 运行时配置
    ├── settings.yaml          # base_dir 等配置
    ├── guard_rules.yaml
    └── command_mode.yaml
```

---

### 数据库分类原则

| 数据类型 | 存储位置 | 访问权限 | 示例 |
|:---|:---|:---|:---|
| **Skill 学习数据** | `skills/*/skill.duckdb` (单文件多表) | 单一 Skill 读写 | 别名、案例、缓存 |
| **共享快照数据** | `db/snapshots.duckdb` | 所有 Skill 只读 | show 命令输出 |
| **共享拓扑数据** | `db/topology.duckdb` | 所有 Skill 只读 | 设备、连接关系 |
| **共享审计日志** | `db/audit_logs.duckdb` | 所有 Skill 写入 | 命令执行记录 |

---

## 🧠 Agentic Learning 设计（简化版）

### 设计理念

**核心原则**: 每个 Skill 专注学习一件事，避免过度设计

- ✅ **Query Skill**: 学习用户语言习惯（别名、查询模板）
- ✅ **Expert Skill**: 学习历史诊断案例（症状 + 诊断 + 结论）
- ✅ **简单有效**: 直接记录 + 直接检索 + 时间过滤

**数据库策略**: 每个 Skill 使用**单一 `skill.duckdb` 文件**，通过**不同表名**隔离功能

---

### 两层知识体系

#### Layer 1: 用户静态知识库（人工维护）

**位置**: `.olav/knowledge/`  
**性质**: 静态、通用、人工编写  
**内容**: 协议标准、最佳实践、公司网络设计文档

```
.olav/knowledge/
├── bgp_troubleshooting.md      # BGP 排查手册（人工编写）
├── aliases.md                  # 用户定义的别名词典
├── command-templates.md        # 常用命令模板
└── solutions/
    ├── mtu_mismatch.md         # MTU 问题解决方案
    └── route_leaking.md        # 路由泄漏修复方案
```

**特点**:
- ✅ 永久有效的通用知识
- ✅ 人工维护，质量有保证
- ✅ Agent 通过 RAG 检索使用

---

#### Layer 2: Agent 动态案例库（自动积累）

**位置**: `skills/*/skill.duckdb`（各 Skill 独立）  
**性质**: 动态、具体、自动记录  
**内容**: Agent 执行任务时自动学习的数据

**对比**:

| 维度 | 用户 KB (`.olav/knowledge/`) | Agent 学习库 (`skill.duckdb`) |
|:---|:---|:---|
| **来源** | 人工编写 | Agent 自动记录 |
| **内容** | 抽象方法论 | 具体案例/习惯 |
| **更新** | 手动维护 | 每次执行自动追加 |
| **时效性** | 永久有效 | 有时效性（30天过滤） |
| **示例** | "如何排查 BGP 问题" | "2026-01-30 R1 BGP down → MTU" |

---

### Skill 学习数据库设计

#### Network-Query Skill: 学习用户语言习惯

**数据库文件**: `skills/network-query/skill.duckdb`

**表 1: user_aliases（别名映射）**

```sql
CREATE TABLE user_aliases (
    alias TEXT PRIMARY KEY,        -- 用户说的词（如 "核心路由器"）
    canonical TEXT,                -- 规范名称（如 "R1,R2,R3"）
    type TEXT,                     -- 'device', 'site', 'group'
    usage_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 示例数据
INSERT INTO user_aliases VALUES 
('核心路由器', 'R1,R2,R3', 'device', 5, '2026-01-25', '2026-01-30'),
('边缘交换机', 'SW1,SW2,SW3,SW4', 'device', 3, '2026-01-20', '2026-01-29'),
('IDC机房', 'site:Beijing-DC1', 'site', 2, '2026-01-22', '2026-01-28');
```

**表 2: query_templates（查询模板偏好）**

```sql
CREATE TABLE query_templates (
    id UUID PRIMARY KEY DEFAULT uuid(),
    user_query TEXT,               -- 用户原始问法
    normalized_query TEXT,         -- 规范化查询
    sql_template TEXT,             -- SQL 模板
    usage_count INTEGER DEFAULT 1,
    success_rate REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_query_fts ON query_templates USING FTS(user_query);

-- 示例数据
INSERT INTO query_templates (user_query, sql_template) VALUES
('看一下核心的接口', 'SELECT * FROM v_interfaces WHERE device IN ({devices})'),
('BGP邻居状态', 'SELECT * FROM v_bgp_neighbors WHERE device = {device}');
```

**表 3: intent_cache（精确匹配缓存）**

```sql
CREATE TABLE intent_cache (
    query_text TEXT PRIMARY KEY,       -- 用户查询（精确匹配）
    execution_plan JSON,                -- 执行计划
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hit_count INTEGER DEFAULT 1
);

CREATE INDEX idx_intent_last_used ON intent_cache(last_used DESC);
```

**学习机制**:

```python
async def process_query(user_input: str):
    """Query Agent 处理查询并学习用户习惯"""
    
    # 1. 提取别名
    aliases = extract_entities(user_input)
    
    # 2. 查询已学习的别名映射
    for alias in aliases:
        mapping = db.execute(
            "SELECT canonical FROM user_aliases WHERE alias = ?", 
            [alias]
        ).fetchone()
        
        if not mapping:
            # 首次遇到，推理或询问用户
            mapping = await infer_alias_mapping(alias, user_input)
            # 保存学习结果
            db.execute("""
                INSERT INTO user_aliases (alias, canonical, type) 
                VALUES (?, ?, 'device')
            """, [alias, mapping])
        else:
            # 更新使用统计
            db.execute("""
                UPDATE user_aliases 
                SET usage_count = usage_count + 1, 
                    last_used = CURRENT_TIMESTAMP
                WHERE alias = ?
            """, [alias])
    
    # 3. 翻译为规范 SQL
    sql = translate_with_aliases(user_input, alias_mappings)
    
    # 4. 保存查询模板（用于未来优化）
    db.execute("""
        INSERT INTO query_templates (user_query, sql_template, usage_count)
        VALUES (?, ?, 1)
        ON CONFLICT (user_query) DO UPDATE SET
            usage_count = usage_count + 1,
            last_used = CURRENT_TIMESTAMP
    """, [user_input, sql])
    
    return execute_sql(sql)
```

**实际效果**:

**第 1 次**:
```
用户: "查询核心路由器的接口状态"
Agent: "核心路由器是指哪些设备？（我会记住）"
用户: "R1, R2, R3"
Agent: ✅ 已学习：核心路由器 = R1,R2,R3
      执行 SQL: SELECT * FROM v_interfaces WHERE device IN ('R1','R2','R3')
```

**第 2 次**（自动应用）:
```
用户: "核心路由器有没有 down 的接口？"
Agent: （自动识别别名 "核心路由器" → R1,R2,R3）
      执行 SQL: SELECT * FROM v_interfaces 
                WHERE device IN ('R1','R2','R3') AND status = 'down'
```

---

#### Network-Expert Skill: 学习历史诊断案例

**数据库文件**: `skills/network-expert/skill.duckdb`

**表 1: history_cases（诊断案例库）**

```sql
CREATE TABLE history_cases (
    id UUID PRIMARY KEY DEFAULT uuid(),
    
    -- 症状（用户描述）
    symptom TEXT NOT NULL,             -- 用户描述的问题
    
    -- 诊断过程（简化记录）
    devices_checked JSON,              -- 检查了哪些设备
    commands_used JSON,                -- 执行了哪些命令/工具
    diagnosis_steps TEXT,              -- 诊断步骤摘要
    
    -- 结论
    root_cause TEXT,                   -- 根因（自然语言）
    solution TEXT,                     -- 解决方案
    
    -- 关联数据（用于溯源）
    snapshot_id UUID,                  -- 诊断时的快照 ID
    
    -- 时间信息
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 计算列：案例年龄（天）
    age_days INTEGER GENERATED ALWAYS AS (
        CAST((CURRENT_DATE - created_at::DATE) AS INTEGER)
    ) STORED
);

-- 全文搜索索引
CREATE INDEX idx_symptom_fts ON history_cases USING FTS(symptom);
CREATE INDEX idx_created_at ON history_cases(created_at DESC);

-- 示例数据
INSERT INTO history_cases (symptom, devices_checked, commands_used, root_cause, solution, snapshot_id) 
VALUES (
    'R1 BGP neighbor down',
    '["R1", "R2"]',
    '["show ip bgp summary", "show interface", "ping"]',
    'MTU 不匹配导致 TCP 连接失败',
    '将 R1 Gi0/1 接口 MTU 调整为 1500',
    '550e8400-e29b-41d4-a716-446655440000'
);
```

**学习机制**:

```python
async def diagnose_issue(symptom: str, snapshot_id: UUID):
    """Expert Agent 诊断问题并自动学习"""
    
    # 1. 执行诊断（ReAct Agent）
    result = await react_agent.diagnose(symptom)
    
    # 2. 诊断完成后，自动记录案例
    db.execute("""
        INSERT INTO history_cases 
        (symptom, devices_checked, commands_used, diagnosis_steps, 
         root_cause, solution, snapshot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [
        symptom,
        json.dumps(result.devices_checked),
        json.dumps(result.commands_used),
        result.diagnosis_summary,
        result.root_cause,
        result.solution,
        snapshot_id
    ])
    
    return result
```

**案例检索与应用**:

```python
async def suggest_similar_cases(symptom: str):
    """检索相似历史案例（仅作为参考）"""
    
    # 1. 全文搜索 + 时间过滤（只看最近 30 天）
    cases = db.execute("""
        SELECT symptom, root_cause, solution, diagnosis_steps, 
               created_at, age_days
        FROM history_cases 
        WHERE symptom MATCH ?
          AND age_days <= 30  -- ⚠️ 只参考最近 30 天案例
        ORDER BY created_at DESC 
        LIMIT 3
    """, [symptom]).fetchall()
    
    if not cases:
        return None
    
    # 2. 构建参考上下文（提供给 LLM）
    context = "相似的历史案例（仅供参考，需验证当前状态）：\n\n"
    for case in cases:
        context += f"""
        - 时间: {case.created_at} ({case.age_days} 天前)
          症状: {case.symptom}
          根因: {case.root_cause}
          解决方案: {case.solution}
        """
    
    return context
```

**防止误判的关键设计**:

```python
# LLM 提示词设计
prompt = f"""
你是网络故障诊断专家。

## 当前问题
{symptom}

## 当前网络状态（实时快照）
{current_snapshot_data}

## 历史相似案例（仅供参考）
{similar_cases_context}

⚠️ 重要规则：
1. 历史案例仅作为诊断方向提示，不能直接应用结论
2. 必须在当前快照数据中验证每个假设
3. 如果历史案例提示 "MTU 问题"，你必须：
   - 先查询当前设备的 MTU 配置
   - 验证是否确实存在 MTU 不匹配
   - 而不是直接输出 "解决方案：调整 MTU"

请基于当前状态进行诊断。
"""
```

**实际效果**:

**第 1 次诊断**:
```
用户: "R1 BGP neighbor down"
Agent: （执行完整诊断流程...）
      检查设备: R1, R2
      执行命令: show ip bgp summary, show interface, ping
      根因: MTU 不匹配
      解决方案: 调整接口 MTU 为 1500
      
      ✅ 已记录到案例库 (history_cases 表)
```

**第 2 次遇到类似问题**（30 天内）:
```
用户: "R2 BGP 邻居起不来"
Agent: 检索到相似历史案例（7 天前）：
      - R1 BGP neighbor down → MTU 不匹配
      
      建议优先检查: MTU 配置
      
      正在验证当前状态...
      查询: SELECT mtu FROM v_interfaces WHERE device = 'R2'
      
      结果: MTU 配置正常 (1500)
      继续排查其他可能性...
      （检查路由策略、ACL 等）
```

---

### 数据库文件组织

**简化方案：单文件多表**

```
skills/network-query/
├── SKILL.md
├── scripts/
│   ├── query_database.py
│   └── inspect_schema.py
└── skill.duckdb              # ✅ 单一数据库文件
    ├── user_aliases          # 表 1: 别名映射
    ├── query_templates       # 表 2: 查询模板
    └── intent_cache          # 表 3: Intent Cache

skills/network-expert/
├── SKILL.md
├── scripts/
│   ├── analyze_topology.py
│   └── diagnose_issue.py
└── skill.duckdb              # ✅ 单一数据库文件
    └── history_cases         # 表 1: 诊断案例库
```

**优势**:
- ✅ 简化管理：一个 Skill 一个数据库文件
- ✅ 清晰隔离：通过表名区分不同功能
- ✅ 便于迁移：直接复制 `skill.duckdb` 即可
- ✅ 易于备份：单文件备份策略

---

### 历史案例使用原则

#### 核心理念：信任 LLM 判断力

**设计思路**:
- ✅ **保留所有历史案例**（不做时间窗口过滤）
- ✅ **提供完整时间信息**（让 LLM 自己判断时效性）
- ✅ **排错思路永久有效**（诊断方法论不会过时）
- ⚠️ **提示词引导**（提醒 LLM 注意时间和可靠性）

#### 1. 提供时间戳信息

```sql
-- ✅ 检索所有相似案例（不做时间过滤）
SELECT 
    symptom, root_cause, solution, diagnosis_steps,
    created_at, age_days  -- 案例年龄（天）
FROM history_cases 
WHERE symptom MATCH ?
ORDER BY created_at DESC  -- 优先展示最新案例
LIMIT 10
```

#### 2. 必须实时验证

```python
# ❌ 错误做法：直接应用历史结论
if similar_case.root_cause == "MTU mismatch":
    return "建议：调整 MTU 为 1500"

# ✅ 正确做法：在当前快照验证
if similar_case.root_cause == "MTU mismatch":
    # 查询当前 MTU 配置
    current_mtu = query_snapshots("""
        SELECT interface, mtu 
        FROM v_interfaces 
        WHERE device = ? 
    """, [device])
    
    # 验证假设
    if has_mtu_mismatch(current_mtu):
        return "确认：MTU 不匹配（与历史案例一致）"
    else:
        return "MTU 正常，继续排查其他可能性..."
```

#### 3. 提示词强制约束

```python
system_prompt = """
你是网络诊断专家。

核心规则（必须遵守）：
1. 历史案例仅作为"诊断方向提示"，不是标准答案
2. 每个假设都必须在当前快照数据中验证
3. 禁止直接套用历史案例的结论
4. 当前快照数据 > 历史案例

示例：
- ❌ 错误: "根据历史案例，问题是 MTU 不匹配，建议调整 MTU"
- ✅ 正确: "历史案例提示可能是 MTU 问题，正在验证...查询当前 MTU 配置...MTU 正常，排除此可能"
"""
```

---

### DataGateway 接口更新

```python
# lib/data_gateway.py 新增 Skill 学习数据访问方法

class DataGateway:
    
    # ==================== Skill 学习数据 API ====================
    
    def save_user_alias(self, skill_name: str, alias: str, canonical: str, type: str = "device"):
        """保存用户别名学习"""
        skill_db = self.skills_dir / skill_name / "skill.duckdb"
        skill_db.parent.mkdir(parents=True, exist_ok=True)
        
        conn = duckdb.connect(str(skill_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_aliases (
                alias TEXT PRIMARY KEY,
                canonical TEXT,
                type TEXT,
                usage_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT INTO user_aliases (alias, canonical, type)
            VALUES (?, ?, ?)
            ON CONFLICT (alias) DO UPDATE SET
                usage_count = usage_count + 1,
                last_used = CURRENT_TIMESTAMP
        """, [alias, canonical, type])
        conn.close()
    
    def get_user_alias(self, skill_name: str, alias: str) -> Optional[str]:
        """获取别名映射"""
        skill_db = self.skills_dir / skill_name / "skill.duckdb"
        if not skill_db.exists():
            return None
        
        conn = duckdb.connect(str(skill_db), read_only=True)
        result = conn.execute(
            "SELECT canonical FROM user_aliases WHERE alias = ?", 
            [alias]
        ).fetchone()
        conn.close()
        return result[0] if result else None
    
    def save_diagnosis_case(
        self, 
        symptom: str, 
        devices: list, 
        commands: list,
        root_cause: str,
        solution: str,
        snapshot_id: UUID
    ):
        """保存诊断案例"""
        skill_db = self.skills_dir / "network-expert" / "skill.duckdb"
        skill_db.parent.mkdir(parents=True, exist_ok=True)
        
        conn = duckdb.connect(str(skill_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history_cases (
                id UUID PRIMARY KEY DEFAULT uuid(),
                symptom TEXT NOT NULL,
                devices_checked JSON,
                commands_used JSON,
                root_cause TEXT,
                solution TEXT,
                snapshot_id UUID,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                age_days INTEGER GENERATED ALWAYS AS (
                    CAST((CURRENT_DATE - created_at::DATE) AS INTEGER)
                ) STORED
            )
        """)
        conn.execute("""
            INSERT INTO history_cases 
            (symptom, devices_checked, commands_used, root_cause, solution, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [symptom, json.dumps(devices), json.dumps(commands), root_cause, solution, str(snapshot_id)])
        conn.close()
    
    def search_similar_cases(self, symptom: str, max_age_days: int = 30) -> list[dict]:
        """检索相似诊断案例"""
        skill_db = self.skills_dir / "network-expert" / "skill.duckdb"
        if not skill_db.exists():
            return []
        
        conn = duckdb.connect(str(skill_db), read_only=True)
        results = conn.execute("""
            SELECT symptom, root_cause, solution, created_at, age_days
            FROM history_cases
            WHERE symptom MATCH ?
              AND age_days <= ?
            ORDER BY created_at DESC
            LIMIT 5
        """, [symptom, max_age_days]).fetchall()
        conn.close()
        
        return [
            {
                "symptom": r[0],
                "root_cause": r[1],
                "solution": r[2],
                "created_at": r[3],
                "age_days": r[4]
            }
            for r in results
        ]
```

---

## 🎯 Agentic Learning 总结

### 各 Skill 的学习目标

| Skill | 学什么 | 存储位置 | 表名 | 学习效果 |
|:---|:---|:---|:---|:---|
| **network-query** | 用户语言习惯 | `skill.duckdb` | `user_aliases`<br>`query_templates`<br>`intent_cache` | 理解 "核心路由器"<br>记住常用查询 |
| **network-expert** | 历史诊断案例 | `skill.duckdb` | `history_cases` | 参考类似故障<br>加速诊断流程 |
| **network-inspector** | 巡检模式 | `skill.duckdb` | `inspection_tasks`<br>`anomaly_patterns` | 识别异常模式<br>优化巡检策略 |

### 学习 vs 时效性平衡

| 维度 | 设计策略 | 实现方式 |
|:---|:---|:---|
| **避免过时数据** | 时间窗口过滤 | `WHERE age_days <= 30` |
| **必须实时验证** | 强制查询当前快照 | 提示词约束 + 代码逻辑 |
| **案例仅供参考** | 不直接应用结论 | "诊断方向提示" |
| **持续优化** | 自动记录新案例 | 每次诊断自动保存 |

### 优势总结

1. **简单实用**
   - 单文件多表，管理简单
   - 直接记录 + 直接检索
   - 无需复杂的模式蒸馏

2. **学习有效**
   - 别名学习：立即提升体验
   - 案例积累：加速故障诊断
   - 自动进化：无需人工维护

3. **防止误判**
   - 30 天时间窗口
   - 必须实时验证
   - 提示词强制约束

4. **易于扩展**
   - 新 Skill 只需添加新表
   - 统一 DataGateway 接口
   - 跨平台兼容
| **Skill 私有记忆** | `skills/*/memory.duckdb` | 单一 Skill 读写 | 故障诊断历史 |
| **Skill 私有状态** | `skills/*/state.duckdb` | 单一 Skill 读写 | Netbox 同步状态 |
| **共享快照数据** | `db/snapshots.duckdb` | 所有 Skill 只读 | show 命令输出 |
| **共享拓扑数据** | `db/topology.duckdb` | 所有 Skill 只读 | 设备、连接关系 |
| **共享审计日志** | `db/audit_logs.duckdb` | 所有 Skill 写入 | 命令执行记录 |

---

### Skill 私有数据库设计

#### 1. network-query/cache.duckdb (Intent Cache)

```sql
-- Intent Cache: 精确匹配查询 → 执行计划
CREATE TABLE intent_cache (
    query_text TEXT PRIMARY KEY,       -- 用户查询 (精确匹配)
    execution_plan JSON,                -- 执行计划 { steps: [...] }
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hit_count INTEGER DEFAULT 1
);

CREATE INDEX idx_last_used ON intent_cache(last_used DESC);
```

**使用场景**:
- 缓存命中 → 直接执行 SQL，无 LLM 推理
- 缓存未命中 → 交由 Orchestrator

---

#### 2. network-expert/memory.duckdb (故障诊断记忆)

```sql
-- 故障诊断案例库
CREATE TABLE diagnosis_cases (
    id UUID PRIMARY KEY DEFAULT uuid(),
    symptom TEXT,                       -- 症状描述
    root_cause TEXT,                    -- 根因
    solution TEXT,                      -- 解决方案
    devices JSON,                       -- 涉及设备
    commands JSON,                      -- 诊断命令
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 自动扩展历史
CREATE TABLE expansion_history (
    id UUID PRIMARY KEY,
    initial_scope JSON,                 -- 初始范围 ["R1"]
    expanded_scope JSON,                -- 扩展范围 ["R1", "R2", "R3"]
    reason TEXT,                        -- 扩展原因
    created_at TIMESTAMP
);

CREATE INDEX idx_symptom_fts ON diagnosis_cases USING FTS(symptom);
```

**使用场景**:
- 故障诊断时查询历史类似案例
- 记录自动扩展决策用于学习

---

#### 3. network-inspector/inspection_cache.duckdb

```sql
-- 巡检任务缓存
CREATE TABLE inspection_tasks (
    id UUID PRIMARY KEY,
    schedule TEXT,                      -- cron 表达式
    devices JSON,
    commands JSON,
    last_run TIMESTAMP,
    next_run TIMESTAMP
);

-- 巡检报告缓存
CREATE TABLE inspection_reports (
    id UUID PRIMARY KEY,
    task_id UUID,
    snapshot_id UUID,
    anomalies JSON,                     -- 异常发现
    score INTEGER,                      -- 健康评分
    created_at TIMESTAMP
);
```

---

#### 4. netbox-integration/sync_state.duckdb (未来)

```sql
-- Netbox 同步状态
CREATE TABLE sync_state (
    resource_type TEXT,                 -- 'device', 'interface', 'ip'
    resource_id TEXT,
    last_sync TIMESTAMP,
    checksum TEXT,                      -- 用于检测变更
    PRIMARY KEY (resource_type, resource_id)
);
```

---

#### 5. textfsm-learning/templates.duckdb (未来)

```sql
-- 学习的 TextFSM 模板
CREATE TABLE learned_templates (
    id UUID PRIMARY KEY,
    platform TEXT,                      -- 'cisco_ios'
    command TEXT,                       -- 'show platform hardware'
    template_text TEXT,                 -- TextFSM 模板内容
    confidence REAL,                    -- 模板置信度
    examples JSON,                      -- 训练样本
    created_at TIMESTAMP
);
```

---

### 共享数据库设计

#### 1. db/snapshots.duckdb (全局快照数据)

```sql
-- 快照元数据
CREATE TABLE snapshot_metadata (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMP,
    total_devices INTEGER,
    total_commands INTEGER,
    status TEXT                         -- 'complete', 'partial', 'failed'
);

-- 设备快照数据 (Bronze Layer - 原始输出)
CREATE TABLE device_snapshots (
    id UUID PRIMARY KEY,
    snapshot_id UUID,
    device TEXT,
    platform TEXT,
    command TEXT,
    raw_output TEXT,
    timestamp TIMESTAMP
);

-- 解析后的视图 (Silver Layer - 结构化)
CREATE VIEW v_interfaces AS 
SELECT * FROM read_parquet('data/exports/*/parsed/interfaces.parquet');

CREATE VIEW v_bgp_neighbors AS
SELECT * FROM read_parquet('data/exports/*/parsed/bgp.parquet');

-- 更多视图...
```

**只读访问**: 所有 Skill 通过 `data_gateway.query_snapshots()` 查询

---

#### 2. db/topology.duckdb (拓扑数据)

```sql
-- 设备节点
CREATE TABLE devices (
    name TEXT PRIMARY KEY,
    platform TEXT,
    role TEXT,                          -- 'core', 'edge', 'access'
    site TEXT,
    management_ip TEXT,
    metadata JSON
);

-- 连接关系 (CDP/LLDP)
CREATE TABLE connections (
    id UUID PRIMARY KEY,
    source_device TEXT,
    source_interface TEXT,
    target_device TEXT,
    target_interface TEXT,
    protocol TEXT,                      -- 'CDP', 'LLDP'
    discovered_at TIMESTAMP
);

-- IP 地址分配
CREATE TABLE ip_allocations (
    ip_address TEXT PRIMARY KEY,
    device TEXT,
    interface TEXT,
    subnet TEXT,
    vrf TEXT
);
```

**只读访问**: 所有 Skill 通过 `data_gateway.get_topology()` 查询

---

#### 3. db/audit_logs.duckdb (命令审计)

```sql
-- 命令执行审计
CREATE TABLE command_audit (
    id UUID PRIMARY KEY DEFAULT uuid(),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    skill TEXT,                         -- 'network-query'
    device TEXT,
    command TEXT,
    user TEXT,
    status TEXT,                        -- 'success', 'failed', 'blocked'
    error TEXT
);

CREATE INDEX idx_timestamp ON command_audit(timestamp DESC);
CREATE INDEX idx_device ON command_audit(device);
```

**写入权限**: 所有 Skill 通过 `data_gateway.log_command()` 写入

---

## 🔌 统一数据访问接口 (Data Gateway)

### 核心设计: lib/data_gateway.py

```python
"""
Platform-agnostic Data Gateway
Compatible with: OLAV CLI, Web API, Claude Code, Gemini Agent
"""

from pathlib import Path
import duckdb
import json
from typing import Any, Optional
from datetime import datetime

class DataGateway:
    """统一数据访问接口 - 平台无关
    
    使用方式:
        # OLAV CLI
        gw = DataGateway(Path(".olav"))
        
        # Claude Code
        gw = DataGateway(Path(".claude"))
        
        # Web API
        gw = DataGateway(Path(os.getenv("BASE_DIR", ".olav")))
    """
    
    def __init__(self, base_dir: Path = None):
        """初始化 Data Gateway
        
        Args:
            base_dir: .olav/ 或 .claude/ 或 .gemini/ 根目录
        """
        self.base_dir = base_dir or Path(".olav")
        self.db_dir = self.base_dir / "db"
        self.skills_dir = self.base_dir / "skills"
        
        # 确保目录存在
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
    
    # ==================== 共享数据层 API ====================
    
    def query_snapshots(self, sql: str, params: list = None) -> list[dict]:
        """查询网络快照数据 (只读)
        
        Args:
            sql: DuckDB SQL 查询
            params: 查询参数
            
        Returns:
            查询结果列表
            
        Example:
            >>> gw.query_snapshots("SELECT * FROM v_interfaces WHERE device = ?", ["R1"])
        """
        conn = duckdb.connect(str(self.db_dir / "snapshots.duckdb"), read_only=True)
        try:
            if params:
                result = conn.execute(sql, params).df()
            else:
                result = conn.execute(sql).df()
            return result.to_dict('records')
        finally:
            conn.close()
    
    def get_topology(self, device: str = None) -> list[dict]:
        """获取拓扑数据 (只读)
        
        Args:
            device: 可选，指定设备名称
            
        Returns:
            拓扑数据
        """
        conn = duckdb.connect(str(self.db_dir / "topology.duckdb"), read_only=True)
        try:
            if device:
                sql = "SELECT * FROM devices WHERE name = ?"
                result = conn.execute(sql, [device]).df()
            else:
                result = conn.execute("SELECT * FROM devices").df()
            return result.to_dict('records')
        finally:
            conn.close()
    
    def log_command(
        self, 
        skill: str, 
        device: str, 
        command: str, 
        status: str,
        error: str = None
    ) -> None:
        """记录命令执行审计 (写入)
        
        Args:
            skill: Skill 名称 (e.g., 'network-query')
            device: 设备名称
            command: 执行的命令
            status: 'success', 'failed', 'blocked'
            error: 错误信息 (可选)
        """
        conn = duckdb.connect(str(self.db_dir / "audit_logs.duckdb"))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS command_audit (
                    id UUID PRIMARY KEY DEFAULT uuid(),
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    skill TEXT,
                    device TEXT,
                    command TEXT,
                    status TEXT,
                    error TEXT
                )
            """)
            conn.execute("""
                INSERT INTO command_audit (skill, device, command, status, error)
                VALUES (?, ?, ?, ?, ?)
            """, [skill, device, command, status, error])
        finally:
            conn.close()
    
    # ==================== Skill 私有数据 API ====================
    
    def get_skill_cache(self, skill_name: str, key: str) -> Optional[dict]:
        """读取 Skill 缓存 (私有数据)
        
        Args:
            skill_name: Skill 名称 (e.g., 'network-query')
            key: 缓存键
            
        Returns:
            缓存值，未找到返回 None
            
        Example:
            >>> plan = gw.get_skill_cache("network-query", "query:show interfaces")
        """
        cache_db = self.skills_dir / skill_name / "cache.duckdb"
        if not cache_db.exists():
            return None
        
        conn = duckdb.connect(str(cache_db), read_only=True)
        try:
            result = conn.execute(
                "SELECT value FROM cache WHERE key = ?", [key]
            ).fetchone()
            return json.loads(result[0]) if result else None
        finally:
            conn.close()
    
    def save_skill_cache(
        self, 
        skill_name: str, 
        key: str, 
        value: dict
    ) -> None:
        """保存 Skill 缓存 (私有数据)
        
        Args:
            skill_name: Skill 名称
            key: 缓存键
            value: 缓存值 (JSON 可序列化)
            
        Example:
            >>> gw.save_skill_cache("network-query", "intent:show bgp", {
            ...     "execution_plan": {"steps": [...]}
            ... })
        """
        cache_db = self.skills_dir / skill_name / "cache.duckdb"
        cache_db.parent.mkdir(parents=True, exist_ok=True)
        
        conn = duckdb.connect(str(cache_db))
        try:
            # 确保表存在
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value JSON,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 插入或更新
            conn.execute("""
                INSERT INTO cache (key, value) VALUES (?, ?)
                ON CONFLICT (key) DO UPDATE SET 
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, [key, json.dumps(value)])
        finally:
            conn.close()
    
    def query_skill_memory(
        self, 
        skill_name: str, 
        sql: str, 
        params: list = None
    ) -> list[dict]:
        """查询 Skill 私有记忆数据库
        
        Args:
            skill_name: Skill 名称 (e.g., 'network-expert')
            sql: SQL 查询
            params: 查询参数
            
        Returns:
            查询结果
            
        Example:
            >>> cases = gw.query_skill_memory(
            ...     "network-expert",
            ...     "SELECT * FROM diagnosis_cases WHERE symptom LIKE ?",
            ...     ["%BGP%"]
            ... )
        """
        memory_db = self.skills_dir / skill_name / "memory.duckdb"
        if not memory_db.exists():
            return []
        
        conn = duckdb.connect(str(memory_db), read_only=True)
        try:
            if params:
                result = conn.execute(sql, params).df()
            else:
                result = conn.execute(sql).df()
            return result.to_dict('records')
        finally:
            conn.close()
    
    def save_skill_memory(
        self,
        skill_name: str,
        table: str,
        data: dict
    ) -> None:
        """写入 Skill 私有记忆数据
        
        Args:
            skill_name: Skill 名称
            table: 表名
            data: 数据字典
            
        Example:
            >>> gw.save_skill_memory("network-expert", "diagnosis_cases", {
            ...     "symptom": "BGP neighbor down",
            ...     "root_cause": "MTU mismatch",
            ...     "solution": "Set MTU to 1500"
            ... })
        """
        memory_db = self.skills_dir / skill_name / "memory.duckdb"
        memory_db.parent.mkdir(parents=True, exist_ok=True)
        
        conn = duckdb.connect(str(memory_db))
        try:
            # 动态插入数据
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            values = list(data.values())
            
            conn.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                values
            )
        finally:
            conn.close()


# ==================== 便捷工厂函数 ====================

def get_gateway(base_dir: str = None) -> DataGateway:
    """获取 DataGateway 实例 (单例模式可选)
    
    Args:
        base_dir: 基础目录路径，默认 .olav
        
    Returns:
        DataGateway 实例
    """
    import os
    base = Path(base_dir or os.getenv("OLAV_BASE_DIR", ".olav"))
    return DataGateway(base)
```

---

### 使用示例

#### 1. OLAV CLI 使用

```python
# src/olav/agents/intent_agent.py
from olav.lib.data_gateway import get_gateway

class IntentAgent:
    def __init__(self):
        self.gw = get_gateway()  # 自动使用 .olav/
    
    async def process_query(self, query: str) -> str:
        # 读取缓存
        cached = self.gw.get_skill_cache("network-query", f"intent:{query}")
        
        if cached:
            # 缓存命中
            return await self._execute_plan(cached["execution_plan"])
        
        # 缓存未命中 → Orchestrator
        result = await self._orchestrate(query)
        
        # 保存缓存
        self.gw.save_skill_cache("network-query", f"intent:{query}", {
            "execution_plan": result["plan"]
        })
        
        return result
```

---

#### 2. Web API 使用 (FastAPI)

```python
# api/main.py
from fastapi import FastAPI
from olav.lib.data_gateway import get_gateway

app = FastAPI()
gw = get_gateway()  # 使用环境变量 OLAV_BASE_DIR

@app.get("/api/devices")
def get_devices():
    """获取所有设备"""
    devices = gw.query_snapshots("SELECT * FROM v_device_status")
    return {"devices": devices}

@app.get("/api/topology/{device}")
def get_device_topology(device: str):
    """获取设备拓扑"""
    topology = gw.get_topology(device=device)
    return {"topology": topology}

@app.post("/api/query")
def execute_query(query: str):
    """执行查询并记录审计"""
    try:
        results = gw.query_snapshots(query)
        gw.log_command("api", "system", query, "success")
        return {"results": results}
    except Exception as e:
        gw.log_command("api", "system", query, "failed", str(e))
        return {"error": str(e)}, 500
```

---

#### 3. Claude Code 使用

```python
# .claude/skills/network-query/scripts/query_database.py
import sys
import json
from pathlib import Path

# 动态检测基础目录
SKILL_DIR = Path(__file__).parent.parent
BASE_DIR = SKILL_DIR.parent.parent  # .claude/

sys.path.insert(0, str(BASE_DIR / "lib"))
from data_gateway import DataGateway

def main(params: dict) -> dict:
    gw = DataGateway(BASE_DIR)
    sql = params["sql"]
    
    try:
        results = gw.query_snapshots(sql)
        return {"status": "success", "results": results}
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    input_data = json.loads(sys.stdin.read())
    result = main(input_data)
    print(json.dumps(result, ensure_ascii=False))
```

---

## 🔄 迁移方案

### Phase 1: Script 重组 (2天)

#### 目标
将统一的 `.olav/scripts/*.py` 移动到各 Skill 内部 `scripts/` 目录。

#### 步骤

**1.1 创建 Skill 内部 scripts 目录**

```bash
# network-query Skill
mkdir -p .olav/skills/network-query/scripts
mkdir -p .olav/skills/network-expert/scripts
mkdir -p .olav/skills/network-inspector/scripts
```

**1.2 移动 Script 文件**

```bash
# network-query 相关 scripts
mv .olav/scripts/query_database.py .olav/skills/network-query/scripts/
mv .olav/scripts/inspect_schema.py .olav/skills/network-query/scripts/
mv .olav/scripts/smart_query.py .olav/skills/network-query/scripts/

# network-expert 相关 scripts
mv .olav/scripts/analyze_topology.py .olav/skills/network-expert/scripts/
mv .olav/scripts/get_device_health.py .olav/skills/network-expert/scripts/
mv .olav/scripts/get_network_summary.py .olav/skills/network-expert/scripts/

# network-inspector 相关 scripts
mv .olav/scripts/find_ip_location.py .olav/skills/network-inspector/scripts/
```

**1.3 更新 SKILL.md 中的 script 路径**

```yaml
# .olav/skills/network-query/SKILL.md
---
name: Network Query
tools:
  - name: query_database
    script: scripts/query_database.py  # ✅ 相对路径
    # 旧: .olav/scripts/query_database.py
    description: "Execute SQL query"
    parameters:
      type: object
      properties:
        sql: {type: string}
      required: ["sql"]
---
```

**1.4 验证 Skill 加载**

```bash
# 测试 Skill 加载
uv run python -c "
from olav.core.skill_loader import get_skill_loader
loader = get_skill_loader()
skill = loader.get_skill('network-query')
print(f'Loaded tools: {[t[\"name\"] for t in skill.frontmatter[\"tools\"]]}')
"
```

**1.5 删除旧的 scripts 目录**

```bash
# 确认所有 script 已迁移后删除
rm -rf .olav/scripts/
```

---

### Phase 2: 数据库分离 (3天)

#### 目标
- 实现 `lib/data_gateway.py`
- 将共享数据库迁移到 `db/` 目录
- 创建 Skill 私有数据库

#### 步骤

**2.1 创建 data_gateway.py**

```bash
# 创建 lib 目录
mkdir -p .olav/lib

# 复制上面的 DataGateway 实现
cat > .olav/lib/data_gateway.py << 'EOF'
# ... (完整的 DataGateway 代码)
EOF
```

**2.2 迁移共享数据库**

```bash
# 创建 db 目录
mkdir -p .olav/db

# 移动现有数据库 (如果存在)
mv .olav/olav.duckdb .olav/db/snapshots.duckdb

# 创建新的共享数据库
uv run python -c "
import duckdb
from pathlib import Path

# 创建 topology.duckdb
conn = duckdb.connect('.olav/db/topology.duckdb')
conn.execute('''
    CREATE TABLE devices (
        name TEXT PRIMARY KEY,
        platform TEXT,
        role TEXT,
        site TEXT,
        management_ip TEXT,
        metadata JSON
    )
''')
conn.close()

# 创建 audit_logs.duckdb
conn = duckdb.connect('.olav/db/audit_logs.duckdb')
conn.execute('''
    CREATE TABLE command_audit (
        id UUID PRIMARY KEY DEFAULT uuid(),
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        skill TEXT,
        device TEXT,
        command TEXT,
        status TEXT,
        error TEXT
    )
''')
conn.close()
"
```

**2.3 创建 Skill 私有数据库**

```bash
# network-query/cache.duckdb
uv run python -c "
import duckdb
from pathlib import Path

cache_db = Path('.olav/skills/network-query/cache.duckdb')
cache_db.parent.mkdir(parents=True, exist_ok=True)

conn = duckdb.connect(str(cache_db))
conn.execute('''
    CREATE TABLE intent_cache (
        query_text TEXT PRIMARY KEY,
        execution_plan JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        hit_count INTEGER DEFAULT 1
    )
''')
conn.close()
"

# network-expert/memory.duckdb
uv run python -c "
import duckdb
from pathlib import Path

memory_db = Path('.olav/skills/network-expert/memory.duckdb')
memory_db.parent.mkdir(parents=True, exist_ok=True)

conn = duckdb.connect(str(memory_db))
conn.execute('''
    CREATE TABLE diagnosis_cases (
        id UUID PRIMARY KEY DEFAULT uuid(),
        symptom TEXT,
        root_cause TEXT,
        solution TEXT,
        devices JSON,
        commands JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.close()
"
```

**2.4 更新代码使用 DataGateway**

```python
# src/olav/agents/intent_agent.py

# ❌ 删除旧代码
# from olav.core.unified_database import UnifiedDatabase
# with UnifiedDatabase() as db:
#     result = db.search_intent_cache(query)

# ✅ 使用新接口
from olav.lib.data_gateway import get_gateway

class IntentAgent:
    def __init__(self):
        self.gw = get_gateway()
    
    async def _check_cache(self, query: str):
        cached = self.gw.get_skill_cache("network-query", f"intent:{query}")
        if cached:
            return cached["execution_plan"]
        return None
    
    async def _save_cache(self, query: str, plan: dict):
        self.gw.save_skill_cache("network-query", f"intent:{query}", {
            "execution_plan": plan
        })
```

**2.5 迁移数据 (可选)**

```bash
# 如果旧数据库有数据需要迁移
uv run python scripts/migrate_intent_cache.py
```

---

### Phase 3: 跨平台测试 (2天)

#### 目标
验证架构可以无缝迁移到 `.claude` 或 `.gemini`。

#### 步骤

**3.1 复制到 .claude**

```bash
# 完整复制
cp -r .olav .claude

# 验证目录结构
tree .claude -L 3
```

**3.2 测试 Skill 加载**

```bash
# 使用 .claude 作为 base_dir
uv run python -c "
from pathlib import Path
import sys
sys.path.insert(0, str(Path('.claude/lib')))

from data_gateway import DataGateway

gw = DataGateway(Path('.claude'))
print('DataGateway initialized successfully')
print(f'Skills dir: {gw.skills_dir}')
print(f'DB dir: {gw.db_dir}')
"
```

**3.3 测试 Script 执行**

```bash
# 测试 network-query Script
echo '{"sql":"SELECT 1 as test"}' | \
  uv run python .claude/skills/network-query/scripts/query_database.py

# 预期输出:
# {"status": "success", "results": [{"test": 1}]}
```

**3.4 测试 Data Gateway API**

```python
# test_claude_gateway.py
from pathlib import Path
import sys
sys.path.insert(0, str(Path('.claude/lib')))

from data_gateway import DataGateway

def test_gateway():
    gw = DataGateway(Path('.claude'))
    
    # 测试保存和读取缓存
    gw.save_skill_cache("network-query", "test_key", {"value": 123})
    cached = gw.get_skill_cache("network-query", "test_key")
    assert cached["value"] == 123, "Cache test failed"
    
    print("✅ Cache test passed")
    
    # 测试审计日志
    gw.log_command("network-query", "R1", "show version", "success")
    print("✅ Audit log test passed")
    
    print("\n🎉 All tests passed! .claude migration successful")

if __name__ == "__main__":
    test_gateway()
```

```bash
uv run python test_claude_gateway.py
```

**3.5 性能对比测试**

```bash
# 测试旧架构 (.olav) vs 新架构 (.claude) 性能
uv run python -c "
import time
from olav.lib.data_gateway import get_gateway

gw = get_gateway()

# 测试 10 次缓存读取
start = time.time()
for i in range(10):
    gw.get_skill_cache('network-query', f'test_{i}')
elapsed = time.time() - start

print(f'10 cache reads: {elapsed*1000:.2f}ms')
print(f'Avg per read: {elapsed*100:.2f}ms')
"
```

**3.6 Claude Code 兼容性测试**

```bash
# 如果有 Claude CLI，测试实际执行
claude-cli --base-dir .claude "show interfaces on R1"
```

---

## 🗑️ 需要淘汰的代码

### 1. 统一 scripts 目录

```bash
# ❌ 删除
.olav/scripts/
├── query_database.py      # → skills/network-query/scripts/
├── analyze_topology.py    # → skills/network-expert/scripts/
├── smart_query.py         # → skills/network-query/scripts/
└── ...

# 删除命令
rm -rf .olav/scripts/
```

---

### 2. UnifiedDatabase 类 (部分功能)

```python
# src/olav/core/unified_database.py

# ❌ 淘汰以下方法 (替换为 DataGateway)
class UnifiedDatabase:
    def search_intent_cache(self, query_text: str):
        # → gw.get_skill_cache("network-query", f"intent:{query}")
        pass
    
    def save_intent_cache(self, query: str, plan: dict):
        # → gw.save_skill_cache("network-query", f"intent:{query}", {"plan": plan})
        pass
    
    def search_cache(self, query_text: str):
        # → gw.get_skill_cache("network-query", f"cache:{query}")
        pass
    
    def save_cache(self, query_text: str, action: dict):
        # → gw.save_skill_cache("network-query", f"cache:{query}", action)
        pass

# ✅ 保留共享数据查询方法 (可选，或迁移到 DataGateway)
class UnifiedDatabase:
    def query(self, sql: str):
        # 可保留作为向后兼容，内部调用 DataGateway
        from olav.lib.data_gateway import get_gateway
        gw = get_gateway()
        return gw.query_snapshots(sql)
```

---

### 3. 硬编码数据库路径

```python
# ❌ 淘汰硬编码路径
NETWORK_SNAPSHOT_PATH = Path(".olav/db/olav.duckdb")
NETWORK_COMMANDS_PATH = Path(".olav/db/commands.duckdb")

# ✅ 使用 DataGateway 自动管理路径
from olav.lib.data_gateway import get_gateway
gw = get_gateway()  # 自动处理路径
```

---

### 4. 旧的缓存表结构

```sql
-- ❌ 删除旧的统一缓存表
-- commands.main.semantic_cache
-- commands.main.intent_cache

-- 这些表已迁移到各 Skill 私有数据库
-- .olav/skills/network-query/cache.duckdb
```

**迁移脚本**:
```bash
# scripts/migrate_old_cache.py
uv run python -c "
import duckdb
from olav.lib.data_gateway import get_gateway

# 读取旧缓存
old_conn = duckdb.connect('.olav/db/olav.duckdb')
old_cache = old_conn.execute('''
    SELECT query_text, execution_plan 
    FROM commands.main.intent_cache
''').fetchall()
old_conn.close()

# 写入新缓存
gw = get_gateway()
for query, plan in old_cache:
    gw.save_skill_cache('network-query', f'intent:{query}', {
        'execution_plan': plan
    })

print(f'Migrated {len(old_cache)} cache entries')
"
```

---

### 5. config/paths.py 中的旧路径常量

```python
# config/paths.py

# ❌ 淘汰
NETWORK_SNAPSHOT_PATH = PROJECT_ROOT / ".olav" / "db" / "olav.duckdb"
NETWORK_COMMANDS_PATH = PROJECT_ROOT / ".olav" / "db" / "commands.duckdb"
USER_CACHE_PATH = PROJECT_ROOT / ".olav" / "cache" / "user_cache.duckdb"

# ✅ 替换为
OLAV_BASE_DIR = PROJECT_ROOT / ".olav"
DB_DIR = OLAV_BASE_DIR / "db"
SKILLS_DIR = OLAV_BASE_DIR / "skills"

SNAPSHOTS_DB = DB_DIR / "snapshots.duckdb"
TOPOLOGY_DB = DB_DIR / "topology.duckdb"
AUDIT_DB = DB_DIR / "audit_logs.duckdb"
```

---

## ✅ 验证清单

### Phase 1 验收

- [ ] 所有 Script 已移动到 Skill 内部 `scripts/` 目录
- [ ] SKILL.md 中的 `script` 路径更新为相对路径
- [ ] Skill 可以正常加载 (运行 `pytest tests/test_skill_loader.py`)
- [ ] 旧的 `.olav/scripts/` 目录已删除

---

### Phase 2 验收

- [ ] `lib/data_gateway.py` 实现完成
- [ ] 共享数据库已迁移到 `db/` 目录
  - [ ] `db/snapshots.duckdb` 存在
  - [ ] `db/topology.duckdb` 存在
  - [ ] `db/audit_logs.duckdb` 存在
- [ ] Skill 私有数据库已创建
  - [ ] `skills/network-query/cache.duckdb` 存在
  - [ ] `skills/network-expert/memory.duckdb` 存在
- [ ] 代码已更新使用 DataGateway
  - [ ] `intent_agent.py` 使用 `gw.get_skill_cache()`
  - [ ] `query_agent_v2.py` 使用 `gw.query_snapshots()`
  - [ ] `analyzer.py` 使用 `gw.query_skill_memory()`

---

### Phase 3 验收

- [ ] `.claude` 目录创建成功
- [ ] Skill 在 `.claude` 中可以加载
- [ ] Script 在 `.claude` 中可以执行
- [ ] DataGateway 在 `.claude` 中正常工作
- [ ] 缓存读写测试通过
- [ ] 审计日志测试通过
- [ ] 性能测试通过 (缓存读取 < 10ms)

---

### 完整 E2E 测试

```bash
# 运行完整测试套件
uv run pytest tests/00_e2e_acceptance_test.py -v

# 代码质量检查
uv run ruff check src/ --fix
uv run ruff format src/
uv run pyright src/

# 跨平台迁移测试
bash scripts/test_claude_migration.sh
```

---

## 📚 参考文档

- [Claude Code Skill 规范](https://docs.anthropic.com/claude/docs/skills)
- [DuckDB 文档](https://duckdb.org/docs/)
- [审计报告](./104_audit_report_claude.md)
- [路线图 v0.9.8](./00_roadmap.md)

---

**文档版本**: v1.0.0  
**最后更新**: 2026-02-01  
**状态**: 架构重构方案 - 待执行
