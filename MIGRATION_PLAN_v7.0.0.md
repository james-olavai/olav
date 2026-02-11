# Query Agent v7.0.0 迁移计划 (零回退)

**状态**: 规划中 → 执行中 → 验证中 → 完成 → 清理

**原则**: 
- ❌ 绝不允许"回退"、"支持v6"、"兼容层"代码存在
- ✅ 完整迁移+测试后立即删除v6代码
- ✅ 每个节点都有验证gate，失败立即修复，不继续

---

## 📋 任务列表

### Phase 1: 测试验证 ✅ (已完成)

- [x] **P1.1: smart_sql_query工具测试**
  - Location: `.olav/shared/tools/smart_sql_query.py`
  - Tests:
    - [x] Schema自动探索 (`explain_only=true`)
    - [x] SQL执行 (`sql="SELECT..."`)
    - [x] 错误处理 (invalid SQL)
  - Result: ✅ All tests pass

- [x] **P1.2: 数据库初始化测试**
  - Location: `scripts/init_database.py`
  - Tests:
    - [x] Schema创建 (10个标准表)
    - [x] 测试数据导入 (6个设备)
    - [x] 表验证 (行数、字段)
  - Result: ✅ Database ready

- [x] **P1.3: 工具集成测试 (Tool wrapper)**
  - Location: `.olav/skills/network-query/tools/smart_sql_query.py`
  - Tests:
    - [x] Tool能否被subprocess调用
    - [x] JSON输入输出格式
  - Result: ✅ Tool callable

### Phase 2: 迁移Query Agent → v7.0.0 (进度: 0%)

- [ ] **P2.1: 替换SKILL.md配置**
  - Current: `.olav/skills/network-query/SKILL.md` (443行)
  - Target: `.olav/skills/network-query/SKILL_v7.md` (40行)
  - Action: 直接替换（无并存期）
  - Gate: Query Agent能否加载新SKILL.md？
  - Commands:
    ```bash
    cp .olav/skills/network-query/SKILL.md .olav/skills/network-query/SKILL_v6_DELETED.md.bak
    cp .olav/skills/network-query/SKILL_v7.md .olav/skills/network-query/SKILL.md
    ```
  - Verification:
    ```bash
    uv run python -c "
    from olav.core.skill_loader import get_skill_loader
    loader = get_skill_loader()
    skill = loader.get_skill('network-query')
    assert skill is not None
    assert 'smart_sql_query' in str(skill.frontmatter['tools'])
    print('✅ SKILL.md loaded correctly')
    "
    ```

- [ ] **P2.2: 更新Query Agent工具列表**
  - Replace: `query_database + inspect_schema`
  - With: `smart_sql_query`
  - File: `.olav/skills/network-query/SKILL.md` (tools section)
  - Verification:
    ```bash
    uv run olav ask "有多少个设备?" 2>&1 | grep -E "(smart_sql_query|2 border)"
    ```

- [ ] **P2.3: 测试Query Agent基础功能**
  - Test 1: 简单计数
    ```bash
    uv run olav ask "有多少个设备?" 
    # Expected: "6 devices"
    ```
  - Test 2: 过滤查询
    ```bash
    uv run olav ask "列出所有border设备"
    # Expected: R1, R2
    ```
  - Test 3: 复杂查询
    ```bash
    uv run olav ask "统计每个site有多少个设备"
    # Expected: LAB: 6
    ```
  - Gate: 3个测试全部通过？

- [ ] **P2.4: E2E测试**
  - Location: `tests/e2e/test_real_scenarios.py`
  - Add new tests:
    ```python
    @pytest.mark.asyncio
    async def test_smart_sql_query_simple_count(self):
        """Query Agent using smart_sql_query - simple count"""
        result = await orchestrate_query("有多少个设备?")
        assert "6" in str(result)
    
    @pytest.mark.asyncio
    async def test_smart_sql_query_filter(self):
        """Query Agent using smart_sql_query - filtered query"""
        result = await orchestrate_query("border设备有哪些?")
        assert "R1" in str(result)
    
    @pytest.mark.asyncio
    async def test_smart_sql_query_aggregation(self):
        """Query Agent using smart_sql_query - aggregation"""
        result = await orchestrate_query("统计设备数量按role")
        assert "border" in str(result).lower()
    ```
  - Commands:
    ```bash
    uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_smart_sql_query_* -v
    ```
  - Gate: 3个E2E测试全部PASS？

### Phase 3: 迁移其他SubAgents （进度: 0%）

### Phase 3: 验证其他SubAgents正常工作 (进度: 0%)

**Context:** 检查发现network-analysis、network-inspection、network-cli使用了query_database
- 决策：保留query_database/inspect_schema工具（其他Agent仍需要）
- 目标：确保smart_sql_query替换不会影响现有Agent

- [ ] **P3.1: 验证network-analysis正常工作**
  - Current SKILL: `.olav/skills/network-analysis/SKILL.md`
  - Tools: query_database, nornir_execute, list_devices
  - Test: 健康分析查询不受smart_sql_query替换影响
  - Verification: 
    ```bash
    uv run olav query "LAB网络的健康状况"
    # 应该路由到network-analysis并执行query_database
    ```

- [ ] **P3.2: 验证network-inspection正常工作**
  - Current SKILL: `.olav/skills/network-inspection/SKILL.md`
  - Tools: inspect_schema, query_database, discover_data
  - Test: 检查报告生成不受smart_sql_query替换影响
  - Verification:
    ```bash
    uv run olav query "生成网络检查报告"
    # 应该路由到network-inspection并执行query_database
    ```

- [ ] **P3.3: 验证network-cli正常工作**
  - Current SKILL: `.olav/skills/network-cli/SKILL.md`
  - Tools: nornir_execute, query_database, list_devices
  - Test: CLI执行能力不受smart_sql_query替换影响
  - Verification:
    ```bash
    uv run olav query "执行show version"
    # 应该路由到network-cli并执行nornir_execute
    ```

### Phase 4: 完整功能测试 (进度: 0%)

- [ ] **P4.1: 回归测试 (所有Query类场景)**
  - Run all Query-related E2E tests:
    ```bash
    uv run pytest tests/e2e/test_real_scenarios.py -k "query" -v
    ```
  - Gate: 全部通过？

- [ ] **P4.2: Orchestrator集成测试**
  - Route detection:
    ```bash
    uv run olav ask "简单查询" | grep "route.*query"
    uv run olav ask "复杂分析" | grep "route.*expert"
    # 验证Orchestrator正确路由
    ```

- [ ] **P4.3: CLI SubAgent功能测试**
  - 需要确保CLI SubAgent不受影响
  - Test query + CLI混合：
    ```bash
    uv run olav ask "查询所有设备然后ping它们"
    # 验证依然能正确路由到CLI
    ```

- [ ] **P4.4: 缓存重建**
  - Clear intent cache (Query Agent使用的cache刷新):
    ```bash
    rm .olav/skills/network-query/skill.duckdb
    # 新一次查询会重建cache
    ```
  - Test: 缓存是否正确重建

### Phase 5: 最终清理 (零回退) (进度: 0%)

**重要**: 因为network-analysis、network-inspection、network-cli仍使用query_database和inspect_schema，这些工具MUST保留

- [ ] **P5.1: 确认SKILL.md迁移完全**
  - Verify network-query SKILL.md no longer has query_database/inspect_schema:
    ```bash
    grep "query_database\|inspect_schema" .olav/skills/network-query/SKILL.md
    # 结果应为空
    ```
  - Gate: network-query使用smart_sql_query吗？✅ YES

- [ ] **P5.2: 删除v6 SKILL备份文件**
  - Files to delete:
    - `.olav/skills/network-query/SKILL_v6_DELETED.md.bak` ❌
  - Action:
    ```bash
    rm .olav/skills/network-query/SKILL_v6_DELETED.md.bak
    ```
  - Verification: 只保留SKILL.md

- [ ] **P5.3: 清理v6相关脚本/文档**
  - Files to review and delete:
    - `scripts/*test_query_database*.py` - 如果存在，删除
    - `tests/*v6*.py` - 如果存在，删除
  - Action:
    ```bash
    find . -name "*test_query_database*" -o -name "*test_v6*" | while read f; do rm "$f"; done
    ```

- [ ] **P5.4: 最终验证 - network-query无v6引用**
  - Grep network-query files:
    ```bash
    grep -r "query_database\|inspect_schema" .olav/skills/network-query \
      --include="*.py" --include="*.md" | grep -v "tools/"
    # 结果应为空 (tools/目录存在工具是OK的，其他agent会用)
    ```
  - Gate: 必须为空

---

## 🔍 质量检查表 (每个Phase必须完成)

### After each Phase - Run:
```bash
# 1. 单元测试
uv run pytest src/ -v --tb=short

# 2. E2E测试（Query Agent相关）
uv run pytest tests/e2e/test_real_scenarios.py -k "query" -v

# 3. 代码质量
uv run ruff check src/ .olav/skills/network-query/ --select=E,W,F

# 4. 类型检查
uv run pyright src/olav/agents/query_agent.py 2>&1 | head -10

# 5. 集成测试
uv run olav ask "有多少个设备?" | grep -E "[0-9]"
```

### Final clean gate:
```bash
# 1. 无v6代码
grep -r "v6\|deprecated\|legacy" src/ .olav/ --include="*.py" | wc -l
# Output: 0

# 2. 所有tests通过
uv run pytest tests/e2e/test_real_scenarios.py -q
# Output: X passed

# 3. 代码lint通过
uv run ruff check src/olav/agents/ --exit-zero | wc -l
# Output: 0 (zero errors)

# 4. 快查询正常
uv run olav ask "border设备?" 2>&1 | grep -E "(R1|R2|success)"
# Output: 包含设备信息
```

---

## 📊 里程碑与Gate

| Phase | Gate条件 | 失败处理 | 预计时间 |
|-------|---------|---------|---------|
| P1 | 所有工具test PASS | ✅ 已完成 | ✅ 完成 |
| P2 | Query Agent 3个查询正常 | 停止，修复SKILL.md | 2小时 |
| P3 | 其他Agent无影响 | 停止，修复迁移 | 1小时 |
| P4 | 所有E2E test PASS | 停止，debug集成 | 2小时 |
| P5 | grep无v6代码 | 停止，确保清理完全 | 1小时 |
| 总计 | 零缺陷交付 | - | **6-8小时** |

---

## ⚠️ 严格规则（零回退协议）

### Rule 1: 一旦迁移，立即删除
```
❌ 不允许:
  - "保留v6作为fallback"
  - "支持v6和v7兼容"
  - "deprecated代码"
  - "_legacy"后缀
  - "if use_v6:" 条件

✅ 允许:
  - 完整测试后删除
  - 代码注释说明"v7替换了v6"
  - Git历史查看旧代码
```

### Rule 2: 测试Gate必须100%通过
```
❌ 不允许:
  - "这个test失败但无关"
  - "稍后修复这个bug"
  - "已知的兼容性问题"

✅ 必须:
  - 所有test PASS或删除test
  - 失败则停止并修复
  - 每个阶段验证后再继续
```

### Rule 3: 每步都要提交git
```bash
P2.1 完成后: git commit -m "migrate: Replace Query SKILL.md v6→v7"
P2.3 完成后: git commit -m "test: Query Agent v7 basic functionality verified"
P4 完成后:  git commit -m "test: All Query Agent v7 E2E tests PASS"
P5 完成后:  git commit -m "refactor: Remove Query Agent v6 code (COMPLETE)"
```

### Rule 4: 无"回退"提交
```
❌ 禁止提交:
  git commit -m "revert: Go back to v6"
  git commit -m "debug: temporary v6 code"
  git revert <提交>

✅ 如出错:
  修复问题 → 提交修复 → 继续前进
  绝不倒退
```

---

## 🚨 红线场景（必须立即停止）

| 场景 | 处理 |
|------|------|
| **"重要业务需要v6"** | ❌ **v7不能降级** - 改进v7或并行运行 |
| **"v7有bug"** | ❌ **不能提交v6** - debug v7直到完整 |
| **"测试失败"** | ❌ **不能跳过** - 修复或删除测试 |
| **"时间紧张"** | ❌ **不能快速迁移** - 严格按阶段执行 |

---

## ✅ 完成标志

迁移完成 = 以下全部为YES:

- [ ] Phase 1-4所有test PASS
- [ ] grep -r "v6" 输出为0
- [ ] 无"deprecated"代码
- [ ] 无fallback到旧工具
- [ ] Git log显示完整迁移链条
- [ ] `uv run olav ask "测试?"` 正常工作
- [ ] 没有SKILL_v6, SKILL_v7等多个版本文件
- [ ] 所有删除操作已提交

---

**迁移团队**: 单人（无协作风险）  
**预计开始**: 现在  
**预计完成**: 8小时内  
**备份策略**: GitHistory（无需保留代码备份）  
**回退策略**: ❌ **无回退 - 仅向前**
