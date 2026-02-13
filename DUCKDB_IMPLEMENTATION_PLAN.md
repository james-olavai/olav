# 🚀 DuckDB Schema 缓存方案 - 实施计划

**开始时间**: 2026-02-13  
**目标**: 实现 DuckDB 持久化schema缓存 + Reload 命令  
**预期耗时**: 2-3 小时  
**性能目标**: 3 倍性能提升 + 持久化缓存 + 版本追踪

---

## 📋 任务清单

### ✅ Phase 1: 底层实现 (新建文件和通用工具)

- [ ] **Task 1.1**: 创建 `src/olav/core/schema_cache.py`
  - [ ] 定义 SchemaCache 类
  - [ ] 实现 initialize() 方法 (创建表 + 初始加载)
  - [ ] 实现 get_schema() 方法 (从缓存读取)
  - [ ] 实现 reload() 方法 (重新加载并更新)
  - [ ] 实现 _load_schema() 私有方法 (查询数据库)
  - **预期代码量**: ~100 行

- [ ] **Task 1.2**: 测试 schema_cache.py
  - [ ] 验证表创建成功
  - [ ] 验证数据写入成功
  - [ ] 验证读取速度 (应该 < 1ms)
  - [ ] 验证重载功能

---

### ✅ Phase 2: 集成到 SubAgent 系统

- [ ] **Task 2.1**: 修改 `src/olav/core/subagent_loader.py`
  - [ ] 导入 SchemaCache 类
  - [ ] 修改 _inject_schema_context() 函数
  - [ ] 改成从缓存读取而不是实时查询
  - [ ] 保留 fallback 逻辑 (缓存失败时降级)
  - **预期改动**: ~10 行

- [ ] **Task 2.2**: 测试 _inject_schema_context()
  - [ ] 验证从缓存正确注入
  - [ ] 验证降级逻辑正常工作
  - [ ] 时间测量 (应该 < 1ms)

---

### ✅ Phase 3: CLI 集成

- [ ] **Task 3.1**: 修改 `src/olav/cli/cli_main.py`
  - [ ] 在 main() 中添加初始化调用
  - [ ] 在交互循环中添加 /reload 命令处理
  - [ ] 确保全局 Orchestrator 重用 (从 IMPLEMENTATION_PLAN.md)
  - **预期改动**: ~20 行

- [ ] **Task 3.2**: 测试 CLI 集成
  - [ ] 启动 OLAV (应该看到初始化消息)
  - [ ] 执行第一个查询 (应该快于之前)
  - [ ] 执行 /reload 命令
  - [ ] 再执行查询 (应该使用新的 schema)

---

### ✅ Phase 4: 完整系统测试

- [ ] **Task 4.1**: E2E 性能测试
  - [ ] 测试启动时延迟 (应该多 8-10s 用于初始化)
  - [ ] 测试查询 1 耗时 (应该 11s 内完成)
  - [ ] 测试查询 2 耗时 (应该 11s 内完成)
  - [ ] 测试查询 3 耗时 (应该 11s 内完成)
  - [ ] 验证性能提升 3 倍

- [ ] **Task 4.2**: 功能测试
  - [ ] 测试多个查询序列
  - [ ] 测试会话隔离 (thread_id)
  - [ ] 测试 /reload 命令
  - [ ] 测试错误处理

- [ ] **Task 4.3**: 数据完整性测试
  - [ ] 查询 schema_cache 表内容
  - [ ] 验证 views 列表正确
  - [ ] 验证 tables 列表正确
  - [ ] 验证 metadata 时间戳更新

---

### ✅ Phase 5: 文档和提交

- [ ] **Task 5.1**: 更新文档
  - [ ] 更新 QUICK_SOLUTION_GUIDE.md (已完成)
  - [ ] 添加用户指南 (/reload 命令说明)
  - [ ] 记录性能改善数据

- [ ] **Task 5.2**: Git 提交
  - [ ] 创建 feature 分支
  - [ ] 提交 schema_cache.py
  - [ ] 提交所有修改
  - [ ] 提交测试结果

---

## 🎯 按优先级排列的工作流

### 立即 (现在开始)

1. ✅ 创建 `schema_cache.py` (Task 1.1)
2. ✅ 修改 `subagent_loader.py` (Task 2.1)
3. ✅ 修改 `cli_main.py` 添加初始化和 reload (Task 3.1)

### 然后 (30 分钟)

4. ✅ 编译测试基础功能 (Task 1.2 + 2.2)
5. ✅ 测试 CLI 启动 (Task 3.2)

### 最后 (30 分钟)

6. ✅ 完整 E2E 性能测试 (Task 4)
7. ✅ 提交代码和文档 (Task 5)

---

## 📊 预期结果

### 启动时

```
$ uv run olav

🚀 OLAV Initializing Orchestrator...
   (Creating global agent instance and schema cache)

[等待 20-25 秒]

📦 Initializing schema cache...
  [查询 views: 2-3s]
  [查询 tables: 2-3s]
  [查询 metadata: 1-2s]
  [写入 DuckDB: < 1s]
✅ Schema cache initialized

✅ Orchestrator ready!

OLAV>
```

### 查询时

```
OLAV> list all devices
[处理 10-12 秒]
✓ 返回 234 个设备列表

OLAV> get ip on R3
[处理 10-12 秒]
✓ 返回 IP 地址

OLAV> /reload
🔄 Reloading schema cache...
  [查询 views: 2-3s]
  [查询 tables: 2-3s]
  [查询 metadata: 1-2s]
✅ Schema cache reloaded

OLAV> list interfaces
[处理 10-12 秒]
✓ 返回接口列表 (using new schema)
```

---

## 💾 代码改动位置

| 文件 | 改动 | 行数 |
|------|------|------|
| `src/olav/core/schema_cache.py` | 创建 (新文件) | 100 |
| `src/olav/core/subagent_loader.py` | 修改 _inject_schema_context() | 10 |
| `src/olav/cli/cli_main.py` | 加初始化 + /reload | 20 |
| `tests/test_schema_cache.py` | 创建 (可选) | 50 |

**总计**: ~130 行代码改动

---

## 🧪 验证检查清单

### 代码质量

- [ ] 无语法错误
- [ ] 无导入错误
- [ ] 所有 import 都存在
- [ ] 代码风格一致

### 功能验证

- [ ] 启动时成功初始化
- [ ] schema_cache 表创建成功
- [ ] 数据正确写入
- [ ] 查询可从缓存读取
- [ ] /reload 命令正常
- [ ] 新数据生效

### 性能验证

- [ ] 初始化时间 < 30s
- [ ] 缓存查询 < 1ms
- [ ] 每个查询 < 15s
- [ ] 3 倍性能提升 ✓

### 集成验证

- [ ] 全局 Orchestrator 重用 ✓
- [ ] thread_id 隔离 ✓
- [ ] 会话历史保留 ✓
- [ ] 错误处理健壮 ✓

---

## 📝 实施笔记

### schema_cache.py 的关键点

- 使用 `duckdb.connect(read_only=True)` 读取缓存 (避免锁冲突)
- 使用 `INSERT ... ON CONFLICT` 原子更新
- 添加 schema_version 字段追踪版本
- 保持 updated_at 时间戳用于审计

### subagent_loader.py 的改动

- 导入 SchemaCache 类
- _inject_schema_context() 改成从缓存读
- 添加 fallback 逻辑 (缓存失败时)
- 保留原有的 format_schema() 函数

### cli_main.py 的改动

- 在 main() 中调用 SchemaCache.initialize()
- 在交互循环中处理 /reload 命令
- 确保全局 Orchestrator 在初始化前创建
- 或者在初始化后创建 (取决于顺序)

### 依赖关系

```
启动流程:
  main()
    ├─ SchemaCache.initialize()  [创建表 + 加载 schema]
    ├─ create_orchestrator()     [创建全局 agent]
    └─ run_interactive_loop_async()
       └─ 循环内 _inject_schema_context()
          └─ SchemaCache.get_schema()  [< 1ms 读取]
```

---

## 🛑 潜在问题和解决方案

### 问题 1: DuckDB 并发写入

**症状**: 多个进程同时写 schema_cache 表时出错

**解决**: 使用 `ON CONFLICT ... DO UPDATE` 自动处理

---

### 问题 2: 缓存失失同步

**症状**: Schema 变化但缓存没更新

**解决**: 提供 /reload 命令手动刷新

---

### 问题 3: 导入循环

**症状**: schema_cache.py 导入 gateway, gateway 导入其他的 ...

**解决**: 延迟导入 (在函数内导入)

---

## ✨ 完成标准

✅ 本方案完成的标准：

1. **代码**
   - ✅ schema_cache.py 创建完成
   - ✅ 所有改动编译无误
   - ✅ 所有测试通过

2. **性能**
   - ✅ 启动时延迟 < 30s
   - ✅ 每个查询 < 15s
   - ✅ 3 倍性能提升验证

3. **功能**
   - ✅ 缓存可读可写
   - ✅ /reload 命令可用
   - ✅ 会话隔离正常
   - ✅ 错误处理健壮

4. **文档**
   - ✅ 代码注释完整
   - ✅ 用户指南更新
   - ✅ 提交信息清晰

---

## 🎯 开始实施

准备好了吗？让我们开始吧！

首先创建 `src/olav/core/schema_cache.py` ...
