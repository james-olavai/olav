# 🎯 Phase 6.2 规划: Plan Mode完整集成

**创建日期**: 2026-02-07  
**目标**: 整合Phase 4.1(/plan基础) + Phase 5(依赖) + Phase 4.2(TodoList)  
**目标时间**: 2026-02-14 (1周)  
**优先级**: ⭐⭐⭐ 最高

---

## 📋 分解工作项

### Phase 6.2.1: /plan命令识别GREEN (今日)
**任务**: 识别和提取/plan前缀，解析用户意图

**实现**:
```python
# src/olav/agents/orchestrator.py - orchestrate_query函数
def orchestrate_query(user_query: str):
    # Step 1: 检测/plan前缀
    is_plan_mode = user_query.startswith("/plan ")
    
    if is_plan_mode:
        # Step 2: 提取意图
        user_intent = user_query[6:].strip()
        
        # Step 3: 进入PLAN_MODE
        return plan_mode_handler(user_intent)
    else:
        # 正常查询模式
        return normal_query_handler(user_query)
```

**RED测试** (已存在于Phase 4.1):
- `test_plan_prefix_detection` ✅
- `test_plan_output_structure` ✅ (但需要增强)
- `test_plan_mode_system_prompt_syntax` ✅

**任务清单**:
- [ ] 更新 orchestrate_query() 检测 /plan 前缀
- [ ] 提取用户意图 (去掉/plan前缀)
- [ ] 进入plan_mode分支
- [ ] 运行RED测试验证

**验收标准**:
```
Input: "/plan 同步网络设备到NetBox"
Output: 确认includes plan intent + user_intent分离
Status: ✅ PASSED (RED tests)
```

---

### Phase 6.2.2: 执行计划输出GREEN (明日)
**任务**: 基于user_intent和Phase 5的dependencies，生成执行计划

**实现**:
```python
# src/olav/agents/orchestrator.py - plan_mode_handler()
async def plan_mode_handler(user_intent: str):
    # Step 1: 从SKILL.md加载dependencies
    skill_config = load_orchestrator_skill()
    dependencies = skill_config.get("collaborative_mode", {}).get("dependencies", [])
    
    # Step 2: 解析依赖图
    graph = _build_dependency_graph(dependencies)
    exec_order = _topological_sort(graph)
    
    # Step 3: 生成执行计划（Markdown）
    plan_markdown = generate_plan_markdown(
        user_intent=user_intent,
        subagents=exec_order,
        tasks=graph["subagents"]
    )
    
    # Step 4: 返回计划（不执行）
    return plan_markdown
```

**生成的计划示例**:
```markdown
# 执行计划: 同步网络设备到NetBox

## 1️⃣ 查询网络设备数据
- SubAgent: query
- 任务: 查询网络数据库获取所有设备
- 输出: network_devices_data (3台设备: R1, R2, R3)

## 2️⃣ 查询NetBox数据库
- SubAgent: netbox
- 任务: 查询NetBox现有数据
- 依赖: network_devices_data (来自步骤1)
- 输出: netbox_data (2台设备: R1, R2)

## 3️⃣ 对比差异并生成报告
- SubAgent: analyzer
- 任务: 对比两个数据源并生成同步建议
- 依赖: network_devices_data, netbox_data (来自步骤1、2)
- 输出: diff_report (新增: R3, 删除: 无)

## 📊 汇总
- 总步骤: 3
- 预计时间: ~2-3分钟
- 风险级别: 低

**确认继续? (Y/n)**
```

**RED测试** (需要新增):
- `test_plan_generates_correct_markdown` (新)
- `test_plan_includes_dependency_info` (新)
- `test_plan_shows_execution_order` (新)

**任务清单**:
- [ ] 创建generate_plan_markdown()函数
- [ ] 整合Phase 5的依赖图信息
- [ ] 格式化步骤说明（1️⃣ 2️⃣ 3️⃣）
- [ ] 包含依赖关系说明
- [ ] 添加汇总和确认提示
- [ ] 运行RED测试验证

**验收标准**:
```
Input: orchestrate_query("/plan 同步网络设备到NetBox")
Output: Markdown plan with:
  ✅ 3个步骤 (query, netbox, analyzer)
  ✅ 依赖关系清晰
  ✅ 输出说明
  ✅ 用户确认提示 "Y/n"
Status: ✅ PASSED (Red tests)
```

---

### Phase 6.2.3: 用户确认流程GREEN (后天)
**任务**: 获取用户确认后执行计划

**实现**:
```python
# src/olav/cli/cli_main.py or src/olav/agents/orchestrator.py
async def execute_with_confirmation(plan_markdown: str, dependencies: list):
    # Step 1: 显示计划
    print(plan_markdown)
    
    # Step 2: 获取用户确认（改进：使用Rich进度条）
    # TODO: Phase 4.2 TodoList中间件应该在这里接管
    user_response = await get_user_confirmation()  
    
    if user_response == "Y":
        # Step 3: 执行计划
        exec_order = _execute_with_dependencies_order(dependencies)
        
        # Step 4: 按顺序执行SubAgent
        context = {}
        for subagent_name in exec_order:
            try:
                result = await execute_subagent(subagent_name, context)
                # 将output存储到context
                output_key = graph["subagents"][subagent_name]["output_context_key"]
                context[output_key] = result
                
                # 显示进度
                print(f"✅ {subagent_name} completed")
            except Exception as e:
                print(f"❌ {subagent_name} failed: {e}")
                # Phase 6.3: 实现错误恢复
                break
        
        # Step 5: 返回最终结果
        return generate_final_report(context)
    else:
        return "取消执行"
```

**RED测试** (需要新增):
- `test_plan_execution_on_confirmation` (新)
- `test_plan_cancellation_on_reject` (新)
- `test_plan_execution_order_correct` (新)

**任务清单**:
- [ ] 实现 get_user_confirmation() 
- [ ] 实现 execute_subagent_with_context()
- [ ] 实现 context传递机制
- [ ] 实现 generate_final_report()
- [ ] 处理用户拒绝的情况
- [ ] 运行RED测试验证

**验收标准**:
```
User input: "Y"
Execution: query → netbox → analyzer (按顺序)
Context passing: ✅ 每个SubAgent接收前面的context
Output: 最终报告包含diff_report
Status: ✅ PASSED (RED tests)
```

---

## 🔄 Phase 6.2 完整流程

```
User Input
  ↓
"/plan 同步网络设备到NetBox"
  ↓
[6.2.1] /plan命令识别 ✢
  ↓
提取意图: "同步网络设备到NetBox"
  ↓
[6.2.2] 执行计划输出 ✢
  ├─ 加载dependencies
  ├─ 构建依赖图
  ├─ 拓扑排序
  └─ 生成Markdown计划
  ↓
显示计划给用户
```
```
  ↓
[6.2.3] 用户确认流程 ✢
  ├─ 等待用户输入 (Y/n)
  ├─ 如果Y:
  │   ├─ query SubAgent → network_devices_data
  │   ├─ netbox SubAgent → netbox_data
  │   ├─ analyzer SubAgent → diff_report
  │   └─ 生成最终报告
  └─ 如果n:
      └─ 取消执行
  ↓
返回结果
```

---

## 📝 RED测试集 (Phase 6.2)

### 已有 (从Phase 4.1)
```python
tests/e2e/test_plan_command_phase1.py:
  ✅ test_plan_prefix_detection
  ✅ test_planning_prompt_enhancement
  ✅ test_plan_output_structure
  ✅ test_netbox_sync_plan_keywords
  ✅ test_plan_mode_system_prompt_syntax
  ✅ test_orchestrator_receives_plan_enhanced_query
  ✅ test_plan_mode_recognizable_in_different_queries
```

### 新增 (Phase 6.2)
```python
tests/e2e/test_plan_command_phase2.py:  (新文件)
  
  # Phase 6.2.1: /plan命令识别
  👁️ test_plan_prefix_extraction
  👁️ test_plan_intent_parsing
  
  # Phase 6.2.2: 执行计划输出
  👁️ test_plan_generates_correct_markdown
  👁️ test_plan_includes_dependency_info
  👁️ test_plan_shows_execution_order
  
  # Phase 6.2.3: 用户确认流程
  👁️ test_plan_execution_on_confirmation
  👁️ test_plan_cancellation_on_reject
  👁️ test_plan_execution_order_correct (依赖Phase 5)
```

**总计**: 10个新RED测试

---

## 📊 依赖关系

```
Phase 4.1 (Plan命令基础) ✅
  ↓
Phase 5 (声明式依赖) ✅
  ↓
Phase 6.2 (Plan Mode完整集成) ⏳
  ├─ Phase 6.2.1: /plan识别
  ├─ Phase 6.2.2: 计划输出
  └─ Phase 6.2.3: 用户确认
  ↓
Phase 6.3 (错误恢复) ⏳
  ↓
Phase 6.4 (性能测试) ⏳
```

---

## 🎯 验收标准 (Phase 6.2 完成时)

### 功能完整性
- ✅ /plan前缀识别
- ✅ 用户意图提取
- ✅ 依赖图集成
- ✅ 计划Markdown生成
- ✅ 用户确认流程
- ✅ SubAgent按序执行
- ✅ Context正确传递

### 代码质量
- ✅ 10+ RED测试通过
- ✅ 代码注释完整
- ✅ 向后兼容性保证
- ✅ 错误处理妥善

### 性能
- ✅ 计划生成 <1s
- ✅ SubAgent执行 <5s
- ✅ 内存占用 <100MB

---

## 📅 时间表

| 日期 | 任务 | 状态 |
|------|------|------|
| 2026-02-07 (今日) | Phase 6.2.1规划 | ⏳ |
| 2026-02-08 | Phase 6.2.1实现+RED测试 | ⏳ |
| 2026-02-09 | Phase 6.2.2实现+RED测试 | ⏳ |
| 2026-02-10 | Phase 6.2.3实现+RED测试 | ⏳ |
| 2026-02-11 | 集成测试+文档 | ⏳ |
| 2026-02-12 | 最终验证+清理 | ⏳ |
| 2026-02-14 目标完成 | Phase 6.2 GREEN | ⏳ |

---

## 💡 关键技术点

### 1. Plan模式vs执行模式的区分

```python
# ❌ 错误
"/plan 同步设备" → 立即执行同步

# ✅ 正确
"/plan 同步设备" → 显示计划 → 等待用户确认 → 执行
```

### 2. Dependencies信息展示

```python
# 需要在计划中清晰展示
Step 2 (netbox SubAgent):
  依赖: network_devices_data (来自步骤1)
  这样用户理解why步骤顺序is [query, netbox, analyzer]
```

### 3. Context传递验证

```python
# 每个SubAgent执行前检查required context
if not all(key in context for key in required_keys):
    raise MissingContextError(f"Missing: {required_keys}")
```

---

## 🔗 相关文件参考

- Phase 4.1: `tests/e2e/test_plan_command_phase1.py`
- Phase 5: `tests/e2e/test_declarative_dependencies.py`
- Phase 5 REFACTOR: `src/olav/core/dependency.py`
- Phase 4.2: `.olav/skills/orchestrator/SKILL.md` (TodoList配置)

---

**版本**: Phase 6.2 规划 v1.0  
**状态**: 🎯 准备开始实现  
**下次更新**: Phase 6.2.1 完成时
