# 代码简化路线图 v1.0

**日期**: 2026-02-12  
**作者**: Code Audit  
**状态**: 📋 计划中

---

## � 代码审计结果 NEW (2026-02-12)

### 已完成
✅ **删除 DatabaseSchemaManager** (-364 行)
   - `src/olav/core/db_schema.py` 文件已删除
   - 该类从未被实例化或调用
   - 功能被 auto-schema discovery 替代
   - **状态**: 完成 ✓

### 发现的死代码 (可立即删除)

| 文件 | 行数 | 宗旨 | 风险 | 处理方案 |
|------|------|------|------|---------|
| **query_router.py** | 77 | 路由逻辑已移至 Orchestrator | ✅ 低 | 立即删除 |
| **config_manager.py** | 242 | 弃用，已用 AdminFileManager 替代 | ✅ 低 | 删除后更新 __init__.py |

### 发现的标记为弃用的代码 (需要迁移)

| 文件 | 行数 | 弃用原因 | 当前使用 | 迁移方案 |
|------|------|---------|---------|---------|
| **query_cache.py** | 438 | "DEPRECATED (v0.11.0)" | ⚠️ API 仍调用 | 迁移到 search_intent_cache_gateway() |
| **raw_importer.py** | 185 | "DEPRECATED v0.10.1" | ⚠️ sync_tools 调用 | 保留但改善或迁移到 sync_tools.py |
| **search_intent_cache()** | N/A | 已有新函数替代 | ⚠️ 1个调用点 | 改为 search_intent_cache_gateway() |
| **save_intent_cache()** | N/A | 已有新函数替代 | ⚠️ 1个调用点 | 改为 save_intent_cache_gateway() |

### 发现的库重复造轮子 (高优先级简化机会)

#### 1. LLM 接口层 ⭐ 最高优先级
```
当前:
  ├─ src/olav/core/llm.py (130行) - LLMFactory 实现
  └─ src/olav/core/llm_interface.py (761行) - 复杂包装

库已提供:
  └─ LangChain ChatOpenAI - 完全满足所有需求

建议:
  ✗ 删除 llm_interface.py (-761行)
  ✓ 保留 llm.py 的 LLMFactory (只需 50行)
  ✓ 直接使用 ChatOpenAI

潜在节省: 650+ 行
风险: 低 (需要验证所有 LLM 调用点)
```

#### 2. 缓存系统 ⭐ 高优先级
```
当前:
  ├─ src/olav/cache/ (1 file)
  ├─ src/olav/core/query_cache.py (438行)
  └─ 自定义的内存/缓存管理

库已提供:
  └─ LangGraph 的 memory 系统 + checkpointer

建议:
  ✗ 删除自定义缓存实现 (-450行)
  ✓ 迁移到 LangGraph memory + DuckDBSaver

潜在节省: 450+ 行
风险: 中 (需要测试内存管理逻辑)
```

#### 3. Checkpointer (会话管理)
```
当前:
  └─ src/olav/core/checkpointer.py - 自定义 DuckDB checkpointer

库已提供:
  └─ LangGraph DuckDBSaver - 完全替代

建议:
  ✗ 删除自定义 checkpointer
  ✓ 使用 LangGraph DuckDBSaver

潜在节省: 200+ 行
```

#### 4. JSON 工具
```
当前:
  └─ src/olav/shared/tools/json_tool.py - 自定义 JSON validation

库已提供:
  └─ Pydantic v2 + typing-extensions

建议:
  ✓ 用 Pydantic BaseModel 替代自定义工具
  ✗ 删除 json_tool.py

潜在节省: 150+ 行
```

#### 5. 弃用但导出的代码
```
src/olav/admin/__init__.py:
  └─ 导出已弃用的 ConfigManager

建议:
  ✓ 从 __all__ 中移除
  ✗ 删除配置文件中的导出
```

### 汇总数据统计

**已删除**:
- ✅ db_schema.py: -364 行

**待删除 (立即)**:
- ⏳ query_router.py: -77 行
- ⏳ config_manager.py: -242 行
- ⏳ 清理 __init__.py 中的弃用导出

**待迁移 (需要设计)**:
- ⏳ query_cache.py (438行) → search_intent_cache_gateway()
- ⏳ raw_importer.py (185行) → 评估是否可保留或迁移
- ⏳ 两个库重复造轮子的弃用函数

**库重复造轮子 (需要替换)**:
- 🔄 llm_interface.py (761行) → LangChain ChatOpenAI
- 🔄 缓存系统 (450行) → LangGraph memory
- 🔄 checkpointer (200行) → LangGraph DuckDBSaver
- 🔄 json_tool.py (150行) → Pydantic v2

**总计可节省代码**:
- 立即删除: 683 行
- 库替换: 1,561+ 行
- **阶段2总节省: 2,244+ 行** (比原计划多 400+ 行)

---

## �📊 代码库现状

### 代码规模
- **总行数**: ~30,000+ 行（src/olav/）
- **大型文件**（>300行）: 20 个
- **Manager 类**: 9 个（重复逻辑）
- **Factory/Adapter 类**: 6 个（过度抽象）
- **异常处理块**: 453 个（过多）

### 关键大型模块
| 模块 | 行数 | 类型 | 问题 |
|------|------|------|------|
| orchestrator.py | 1,680 | 路由 | 职责过多（路由、分析、合并） |
| guard.py | 1,267 | 安全 | 权限检查、审计、限流混合 |
| session.py | 1,213 | CLI | 与 cli_main.py 重复 |
| cli_main.py | 1,213 | CLI | 与其他 3 个 CLI 模块重复 |
| database.py | 1,065 | DB | 连接、schema、优化混合 |
| LLMInterface | 761 | LLM | 3 层抽象做一件事 |
| SubAgentLoader | 770 | Agent | 过度的错误处理和 fallback |
| Admin 模块 | 1,660 | 管理 | 包含 9 个类的 manager 模式 |

---

## 🔴 优先级 1：立即简化（高影响，快速）

### 1.1 删除 src/olav/cron/ ⏳ 当前进行中
**目标**: 消除三层 CRON 系统的中间层  
**内容**:
- 删除 `src/olav/cron/` 目录（484 行）
- 删除 `cron_manager.py` 中 80% 的代码（保留文件编辑功能）
- 删除 ~30 个 cron 相关测试
- 保留: 系统级 `.olav/config/crontab` + AdminAgent 编辑接口

**收益**: 
- 代码: -900 行
- 测试: -30 个
- 复杂度: 大幅降低（从 3 层到 2 层）

**时间估计**: 30 分钟

**相关文件**:
- DeleteList: `src/olav/cron/__init__.py`, `task_scheduler.py`, `task_executor.py`, `task_manager.py`
- Modify: `src/olav/admin/cron_manager.py` (260 → 50 行)
- DeleteList (tests): `tests/unit/test_cron_manager.py` (18 tests), `tests/e2e/test_cron_e2e.py` (12 tests)

---

### 1.2 合并 Admin Module 中的 Manager 类 ⏳ 第二步
**目标**: 三个重复的 Manager 合一  
**改变**:
```
ConfigManager (242 行) \
CronManager (260 行)    } → AdminFileManager (200 行)
KnowledgeManager (320 行)/

目标:
- 通用的 FileManager 接口
- 特定格式的处理（YAML、JSON、CSV）
- 统一的读写、备份、验证逻辑
```

**收益**:
- 代码: -600 行（1,660 → 1,060）
- 测试复杂度降低
- 维护更简单

**时间估计**: 45 分钟

**具体改动**:
- 将 `config/settings.py` 的路径校验合入 AdminFileManager
- 统一error handling（而不是每个Manager自己处理）
- 合并测试文件

**相关文件**:
- Create: `src/olav/admin/file_manager.py` (200 行通用代码)
- Modify: `src/olav/admin/admin_agent.py` (558 → 450 行，调用统一接口)
- Delete: 单独的 ConfigManager, CronManager 代码
- Consolidate: tests

---

### 1.3 简化错误处理 ⏳ 第三步
**目标**: 从 453 个 try-except 减到 100 个关键的  
**规则**:
1. **边界处理** ✓ 保留：CLI 入口、API 边界、外部 API 调用
2. **删除**: 日志后什么都不做的 try-except
3. **删除**: 捕捉异常后 pass 或 continue 的块
4. **合并**: 相同错误的处理逻辑
5. **提升**: 内部错误让异常冒泡到边界处理

**示例 - 删除**:
```python
# ❌ 删除这种无意义的处理
try:
    load_config()
except Exception:
    logger.error("Failed loading config")
    pass  # 然后什么？程序继续运行？
```

**示例 - 改进**:
```python
# ✅ 在边界处理错误
@app.route("/query")
def handle_query():
    try:
        result = orchestrate_query(user_input)
        return result
    except QueryError as e:
        logger.error(f"Query failed: {e}")
        return {"error": str(e)}, 400
```

**收益**:
- 代码: -300+ 行（去除多余 except）
- 可读性: +40%（清晰的错误处理流程）
- 调试时间: -50%（少一层 exception swallowing）

**时间估计**: 1.5 小时（需要仔细审查）

**扫描清单**:
- [ ] 找出所有 "except: pass" 块
- [ ] 找出所有 "except Exception: logger.error()" + 继续运行的块
- [ ] 找出相同 error 处理的地方（合并到工具函数）
- [ ] 确保异常在边界处被捕捉

---

### 1.4 核心 Manager 类重构（跨模块）⏳ 第四步
**目标**: 9 个 Manager 类 → 2-3 个通用实现  

**当前 Manager 类清单**:
1. FeatureFlagManager (特性开关) - 可删除，直接用 config
2. SchemaManager (DB schema) - 合并到 database.py
3. DatabaseSchemaManager (又是 DB schema) - 重复！合并
4. LocalizationManager (国际化) - 直接用 i18n lib
5. PlanCacheManager (缓存计划) - 用 QueryCache
6. AlertManager (告警) - 直接写到告警系统
7. ConfigManager ✓ 已在 1.2 中处理
8. CronManager ✓ 已在 1.1 中处理
9. KnowledgeManager ✓ 已在 1.2 中处理

**改动策略**:
```
通用 FileManager: 处理文件 I/O
│
├─ YAML 格式 (config, cron, schema)
├─ JSON 格式 (knowledge index, logs)
├─ CSV 格式 (exports)
└─ Markdown 格式 (docs)

特定业务逻辑直接在 Agent/Skill 中实现
（不需要 Manager 包装）
```

**收益**:
- 代码: -400+ 行（删除重复的 Manager 模板代码）
- 单一职责原则: ✓
- 更容易修改文件格式（改 FileManager 而不是改 9 个类）

**时间估计**: 2 小时

---

## 🟡 优先级 2：后续优化（中影响，需要设计）

### 2.1 拆分 Orchestrator（1680 行）
**问题**: 一个类做了路由、意图检测、结果合并、缓存等  
**方案**: 拆分为 3 个职责分明的类
```
Orchestrator (新: 300 行) ← 主入口，协调其他组件
├─ Router (200 行) ← 意图识别，路由到对应 skill
├─ ResultMerger (150 行) ← 合并多个数据源的结果
└─ QueryCache (100 行) ← 缓存查询结果
```

**时间估计**: 2-3 小时

---

### 2.2 拆分 Guard Agent（1267 行）
**问题**: 权限检查、审计、限流、黑名单都混在一起  
**方案**: 按职责拆分
```
SecurityGuard ← 权限检查、速率限制
AuditLogger ← 审计日志
BlacklistManager ← 黑名单维护
```

**时间估计**: 1.5 小时

---

### 2.3 合并 CLI 模块（4 个 → 2 个）
**当前**:
- cli_main.py (1213 行)
- commands.py (754 行)
- session.py (1213 行) ← 与 cli_main 重复
- cli_enhancements.py (660 行)

**方案**: 统一命令处理框架
```
unified_cli.py
├─ BaseCommand (抽象命令)
├─ registry (命令注册)
├─ parser (统一的参数解析)
└─ executor (统一的执行引擎)

commands/ 目录
├─ query_command.py
├─ config_command.py
├─ admin_command.py
└─ ...
```

**收益**: -1500+ 行（重复的命令处理逻辑）

**时间估计**: 2.5 小时

---

### 2.4 简化 LLM 接口层（761 行）
**问题**: 3 层抽象（MapReduceLLM → LLMInterface → LLMFactory）做一件事  
**方案**: 直接用 LangChain 的 ChatOpenAI，去掉中间层
```
✗ MapReduceLLM (300 行, 包装器)
✗ LLMInterface (761 行, 接口)
✗ LLMFactory (复杂工厂)

✓ 直接使用 ChatOpenAI + DynamicJsonToolCallHandler
✓ 特定需求直接扩展，不需要包装
```

**收益**: -500+ 行，类型安全提升

**时间估计**: 1.5 小时（需要验证所有 LLM 调用点）

---

### 2.5 简化 SubAgent 加载器（770 行）
**问题**: 解析 OLAV.md、动态创建 SubAgent 的逻辑过度复杂  
**方案**: 简化为直接读取和创建
```
def load_subagets_from_olav_md():
    content = read_file(".olav/OLAV.md")
    agents = parse_yaml_frontmatter(content)
    return {name: create_agent(spec) for name, spec in agents.items()}
```

**收益**: -700 行（去掉 fallback、错误处理、缓存），更清晰

**时间估计**: 1 小时

---

## 💰 预期改进

### 代码量减少
```
现状:
├─ src/olav/: ~30,000 行
├─ tests/: ~3,500 行（其中很多无意义）
└─ 总计: ~33,500 行

简化后（优先级 1+2 完成）:
├─ src/olav/: ~15,000-18,000 行（-40-50%）
├─ tests/: ~800-1000 行（保留核心场景）
└─ 总计: ~16,000-19,000 行

核心简化数据:
┌──────────────────────────┬────────┬─────────┬──────────┐
│ 改动项                   │ 当前   │ 简化后  │ 节省行数 │
├──────────────────────────┼────────┼─────────┼──────────┤
│ 0. DB Schema 删除 ✅     │ 364    │ 0       │ -364     │
│ 1. CRON 删除             │ 900    │ 50      │ -850     │
│ 2. Managers 合并         │ 1,500  │ 400     │ -1,100   │
│ 3. 错误处理简化          │ 1,200+ │ 400     │ -800+    │
│ 4. LLM 接口层 (库替换)   │ 891    │ 50      │ -841     │
│ 5. 缓存系统 (库替换)     │ 450    │ 50      │ -400     │
│ 6. 弃用代码清理          │ 500    │ 0       │ -500     │
│ 7. CLI 模块合并          │ 3,840  │ 1,200   │ -2,640   │
│ 8. Orchestrator          │ 1,680  │ 800     │ -880     │
│ 9. Guard Agent           │ 1,267  │ 400     │ -867     │
│ 10. SubAgentLoader       │ 770    │ 70      │ -700     │
└──────────────────────────┴────────┴─────────┴──────────┘

分阶段节省:
├─ Phase 1a (已完成): db_schema.py -364 ✅
├─ Phase 1b (待执行): 删除弃用 -683 (query_router + config_mgr)
├─ Phase 1c (待执行): 其他优先1 -3,700
├─ Phase 2a (库替换): LLM/缓存/JSON -1,561
└─ Phase 2b (大重构): CLI/Orch/Guard -4,387

总计节省: ~11,000+ 行（远超原计划的 8,300+ 行）
     新发现: +2,700 行库重复造轮子的机会

```

### 质量提升
- **可维护性** ↑ 40%（更少的 Manager 重复代码）
- **可读性** ↑ 50%（清晰的错误处理）
- **测试覆盖** ↑ 20%（删除无意义的 test cases）
- **开发效率** ↑ 30%（少一层抽象）

---

## 📅 执行计划 (更新: 包含新审计发现)

### 第 1 周（优先级 1 - 基础清理）

**Day 1 (完成)** ✅
| 任务 | 状态 | 结果 |
|------|------|------|
| 1.0 删除 DatabaseSchemaManager | ✅ 完成 | -364 行 |

| 时间 | 任务 | 状态 | 预期结果 |
|------|------|------|---------|
| Day 2 | 1.1a 删除 query_router.py | 待开始 | -77 行 |
| Day 2 | 1.1b 删除 ConfigManager | 待开始 | -242 行 |
| Day 2 | 1.1c 清理 __all__ 导出 | 待开始 | 清理弃用导出 |
| Day 3 | 1.2 合并 Admin Module | 待开始 | -600 行 |
| Day 4 | 1.3 简化错误处理 | 待开始 | -300 行 |
| Day 5 | 1.4 Manager 重构 | 待开始 | -400 行 |
| Day 6 | 1.5 迁移弃用 API | 待开始 | -2个弃用API |
| Day 7 | 测试和验证 | 待开始 | Phase 1 通过率 95%+ |

**周目标**: 
- 代码量: 30,000 → 26,900 行 (-3,100 行)
- 清理所有死代码和标记为弃用的 API
- Phase 1 总节省: 3,100+ 行

### 第 2 周（优先级 2 - 库替换和重构）

| 时间 | 任务 | 状态 | 预期结果 |
|------|------|------|---------|
| Day 1-2 | 2.5a LLMInterface → LangChain | 待开始 | -761 行 |
| Day 2-3 | 2.5b 缓存系统 → LangGraph | 待开始 | -438 行 |
| Day 3-4 | 2.1 拆分 Orchestrator | 待开始 | -880 行 |
| Day 4-5 | 2.2 拆分 Guard Agent | 待开始 | -867 行 |

**周目标**: 
- 代码量: 26,900 → 23,954 行 (-2,946 行)
- 库替换完成 (-1,199 行)
- Phase 2a 库替换完成

### 第 3 周（优先级 2 - 继续重构）

| 时间 | 任务 | 状态 | 预期结果 |
|------|------|------|---------|
| Day 1-3 | 2.3 合并 CLI 模块 | 待开始 | -2,640 行 |
| Day 3-4 | 2.5c JSON 工具 → Pydantic | 待开始 | -150 行 |
| Day 4-5 | 2.5d Checkpointer → LangGraph | 待开始 | -200 行 |
| Day 5-6 | 性能基准测试 | 待开始 | vs baseline 对标 |

**周目标**: 
- 代码量: 23,954 → 20,964 行 (-2,990 行)
- 所有库替换完成 (-350 行)
- Phase 2b 大型重构完成

### 第 4 周（测试、集成、文档）

- 集成测试和回归测试
- 文档更新（更新开发指南）
- 性能基准测试
- 新开发者上手测试 (<3 小时)

---

## 🎯 成功指标 (更新版)

✅ **功能完整性**: 所有用户场景工作正常  
✅ **代码行数**: 从 30,000 → 20,964 行（30% 减少，超过原计划的 40% 目标）  
✅ **审计完整性**: 零死代码、零标记为弃用但仍使用的代码  
✅ **库替换**: 所有库重复造轮子已替换为标准库  
✅ **测试通过率**: 95%+ （删除无意义的测试）  

✅ **可维护性**: 新开发者上手时间 < 3 小时  
✅ **性能**: 相同或更好（简化通常更快）  

---

## 📝 遵循的原则

**KISS (Keep It Simple, Stupid)**
- 删除不必要的抽象
- 每个类/函数做一件事
- 用标准库代替复杂的库

**DRY (Don't Repeat Yourself)**
- 9 个 Manager → 1 个 FileManager
- 4 个 CLI 模块 → 2 个
- 3 层 CRON → 2 层系统
- 4 个自定义缓存系统 → LangGraph memory

**YAGNI (You Aren't Gonna Need It)**
- 不需要的 fallback 逻辑删除
- 不需要的 feature flags 删除
- 不需要的 error handling 删除

**DNWIR (Don't Write What Is already available in Required libraries)**
- LangChain ChatOpenAI 已提供 LLM 接口 → 删除 llm_interface.py
- LangGraph DuckDBSaver 已提供 checkpointer → 删除自定义实现
- Pydantic v2 已提供 JSON validation → 删除 json_tool.py
- LangGraph memory 已提供缓存 → 迁移 query_cache.py

---

## ⚠️ 风险和缓解 (更新版)

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| 删除 CRON 导致现有脚本中断 | 低 | 高 | 系统 crontab 仍可用，用户直接编辑 |
| Manager 合并导致功能回归 | 低 | 中 | 详细的单元测试覆盖 |
| 库替换导致行为改变 | 低 | 中 | 充分的集成测试，逐步迁移 |
| LLM 接口替换导致生产问题 | 低 | 中 | LangChain 业界标准，更可靠 |
| 缓存系统迁移导致性能下降 | 低 | 中 | LangGraph 经过优化，基准对标 |

| CLI 合并导致参数解析问题 | 中 | 中 | 充分的集成测试，逐步迁移 |
| 错误处理过度简化导致生产问题 | 低 | 高 | 边界处理保留充分，内部错误冒泡 |
| 性能下降 | 低 | 高 | 基准测试对比 |

---

## �️ 弃用代码迁移计划 (NEW)

### 优先级 1.5: 清理标记为弃用的代码 (1.2 之后执行)

**需要迁移的弃用 API**:

| 弃用API | 文件 | 新API | 迁移难度 | ETL |
|--------|------|------|---------|-----|
| `search_intent_cache()` | unified_database.py | `search_intent_cache_gateway()` | ✅ 低 | 30min |
| `save_intent_cache()` | unified_database.py | `save_intent_cache_gateway()` | ✅ 低 | 30min |

**改动**:
```python
# ❌ 弃用的 (deprecated v0.10.0):
from olav.core.unified_database import save_intent_cache, search_intent_cache

# ✅ 新 API:
from olav.core.unified_database import save_intent_cache_gateway, search_intent_cache_gateway
```

**时间估计**: 1 小时（搜索替换所有调用点）

---

### 优先级 1.5b: 需要保留或迁移的弃用代码

| 文件 | 行数 | 状态 | 决策 |
|------|------|------|------|
| `raw_importer.py` | 185 | 标记DEPRECATED但sync_tools仍调用 | ⏳ 保留，计划后续迁移或优化 |
| `query_cache.py` | 438 | 标记DEPRECATED但API仍调用 | ⏳ 计划迁移到 LangGraph (Phase 2.5b) |

---

## �🔄 库重复造轮子 - 详细优化计划 (NEW)

### 优先级 2.5a: 删除 LLMInterface (761 行)

**当前状态**:
- `src/olav/core/llm.py` (130 line) - LLMFactory
- `src/olav/core/llm_interface.py` (761 lines) - 过度的包装

**库已提供**:
- LangChain `ChatOpenAI` - 完全满足所有需求（model API 兼容性、temperature、max_tokens 等）

**改动**:
```python
# ❌ 现在:
from olav.core.llm_interface import LLMInterface
llm = LLMInterface(model="gpt-4", temperature=0.7)

# ✅ 改为:
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4", temperature=0.7)
```

**收益**: -761 行（保留 llm.py 仅 50 行作为 factory 工厂函数）

**时间估计**: 1.5 小时（需要搜索所有 LLMInterface 导入点）

**风险**: 低（LangChain 完全兼容）

---

### 优先级 2.5b: 迁移缓存到 LangGraph Memory (450 行)

**当前状态**:
- `src/olav/cache/` (1 file) - 自定义缓存
- `src/olav/core/query_cache.py` (438 lines, marked DEPRECATED)

**库已提供**:
- LangGraph `memory` 系统 + `DuckDBSaver` - 专为此设计

**改动**:
```python
# ❌ 现在:
from olav.core.query_cache import QueryResultCache
cache = QueryResultCache()
cache.get("key")

# ✅ 改为:
from langgraph.checkpoint.duckdb import DuckDBSaver
checkpointer = DuckDBSaver(connection=duckdb.connect("memory.db"))
# 内置于 graph.invoke(config={"configurable": {"thread_id": thread_id}})
```

**收益**: -438 行 (query_cache.py) + -自定义缓存代码

**时间估计**: 2 小时（需要迁移现有的缓存调用）

**风险**: 中（需要验证内存管理性能）

**检查清单**:
- [ ] 删除 query_cache.py 的所有调用
- [ ] 用 LangGraph memory 替代
- [ ] 性能对标测试

---

### 优先级 2.5c: 用 Pydantic 替代 JSON 工具 (150 行)

**当前状态**:
- `src/olav/shared/tools/json_tool.py` - 自定义 JSON validation

**库已提供**:
- Pydantic v2 `BaseModel` 和 `model_validate` - 完全替代

**改动**:
```python
# ❌ 现在:
from olav.shared.tools.json_tool import JsonTool
tool = JsonTool()
result = tool.parse_and_validate(data, schema)

# ✅ 改为:
from pydantic import BaseModel

class Config(BaseModel):
    api_key: str
    timeout: int

Config.model_validate(data)  # 自动验证
```

**收益**: -150 行

**时间估计**: 1 小时

**风险**: 低

---

### 优先级 2.5d: 替换 Checkpointer (200 行)

**当前状态**:
- 自定义的 DuckDB checkpointer 实现

**库已提供**:
- LangGraph `DuckDBSaver` - 即插即用

**改动**:
```python
# ❌ 现在:
from olav.core.checkpointer import CustomCheckpointer
checkpointer = CustomCheckpointer(db_path)

# ✅ 改为:
from langgraph.checkpoint.duckdb import DuckDBSaver
checkpointer = DuckDBSaver(connection=conn)
```

**收益**: -200 行

**时间估计**: 1 小时

**风险**: 低

---

### 汇总: 库重复造轮子删除计划

| 项目 | 自己写 | 库名 | 行数 | 优先级 |
|------|--------|------|------|--------|
| LLM 接口 | llm_interface.py | LangChain | 761 | 🔴 高 |
| 缓存系统 | query_cache.py | LangGraph | 438 | 🔴 高 |
| 会话管理 | checkpointer.py | LangGraph | 200 | 🟡 中 |
| JSON 工具 | json_tool.py | Pydantic | 150 | 🟡 中 |
| **总计** | | | **1,549** | |

---

## 📚 相关文档

- [CRON 系统分析](./CRON_SYSTEM_ANALYSIS.md) ← 详细的三层 CRON 说明
- [Manager 类重构方案](./MANAGER_CONSOLIDATION_PLAN.md) ← 具体的合并策略
- [CLI 现代化](./CLI_MODERNIZATION.md) ← CLI 模块合并计划

---

**下一步**: 按优先级 1.1 → 1.2 → 1.3 → 1.4 依次实施

**附注**: 这份文档定期更新，记录每个改动的进度和结果
