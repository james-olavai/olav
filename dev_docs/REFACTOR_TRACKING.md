# OLAV 重构进度追踪

**项目**: OLAV v0.11 → v2.0 架构重构  
**开始日期**: 2026-02-14  
**预计完成**: 2026-02-28 (2 周)  
**当前阶段**: Phase 0 准备中  
**最后更新**: 2026-02-14 23:00

---

## 📊 总体进度

```
设计阶段: ████████████████████ 100% (已完成)
实施阶段: ░░░░░░░░░░░░░░░░░░░░   0% (未开始)
测试阶段: ░░░░░░░░░░░░░░░░░░░░   0% (未开始)
部署阶段: ░░░░░░░░░░░░░░░░░░░░   0% (未开始)

总体进度: ███████░░░░░░░░░░░░░  35% (设计完成)
```

**关键指标**:
- 设计文档: 5/5 完成 ✅
- 代码实施: 0/4 阶段完成
- 测试覆盖: 0% (目标 >80%)
- 功能验证: 0/10 场景通过

---

## 🎯 里程碑

| 里程碑 | 计划日期 | 实际日期 | 状态 | 负责人 |
|--------|---------|---------|------|--------|
| 📋 设计完成 | 2026-02-14 | 2026-02-14 | ✅ 已完成 | Team |
| 🔧 Phase 0: 清理 | 2026-02-15 | - | 🟡 准备中 | - |
| 🛠️ Phase 1: 工具重构 | 2026-02-20 | - | ⏳ 待开始 | - |
| 🗄️ Phase 2: 数据库整合 | 2026-02-22 | - | ⏳ 待开始 | - |
| 🤖 Phase 3: Agent 切换 | 2026-02-24 | - | ⏳ 待开始 | - |
| ✅ Phase 4: 验收测试 | 2026-02-27 | - | ⏳ 待开始 | - |
| 🚀 生产部署 | 2026-02-28 | - | ⏳ 待开始 | - |

---

## 📅 详细阶段追踪

### Phase 0: 安全与清理（1 天）

**目标**: 备份现有系统，清理死代码，修复安全问题

**计划开始**: 2026-02-15  
**预计耗时**: 1 天  
**当前状态**: 🟡 准备中

#### 任务清单

##### 0.1 Git 备份 & 准备
- [ ] Git commit 当前状态（替代手动备份）
  ```bash
  git add .
  git commit -m "chore: snapshot before v2.0 refactor - design complete"
  git tag v0.11-snapshot
  git push origin main --tags
  ```
  - **责任人**: 待认领
  - **预计时间**: 5 分钟
  - **阻塞项**: 无
  - **说明**: Git 历史即备份，无需手动 tar.gz

- [ ] 安装 python-crontab 依赖
  ```bash
  uv sync
  ```
  - **责任人**: 待认领
  - **预计时间**: 5 分钟
  - **阻塞项**: 无

- [ ] Git 创建重构分支
  ```bash
  git checkout -b refactor/v.10-deepagents
  git push -u origin refactor/v2.0-deepagents
  ```
  - **责任人**: 待认领
  - **预计时间**: 2 分钟
  - **阻塞项**: 无
  - **说明**: 所有重构工作在此分支进行

##### 0.2 修复安全问题
- [ ] 修复 SQL 注入（api/v1/devices.py）
  - **文件**: `src/olav/api/v1/devices.py:45-62`
  - **问题**: 直接拼接 SQL 参数
  - **方案**: 使用参数化查询
  - **责任人**: 待认领
  - **预计时间**: 20 分钟
  - **测试**: `pytest tests/api/test_devices.py -k injection`

##### 0.3 删除死代码
- [ ] 删除 query_optimizer.py (369 行)
  - **路径**: `src/olav/core/query_optimizer.py`
  - **原因**: Never used
  - **影响**: 无（未被导入）
  - **责任人**: 待认领

- [ ] 删除 database_enhancer.py (184 行)
  - **路径**: `src/olav/core/database_enhancer.py`
  - **原因**: Never used
  - **影响**: 无（未被导入）
  - **责任人**: 待认领

- [ ] 删除 quality_checker.py (90 行)
  - **路径**: `src/olav/agents/quality_checker.py`
  - **原因**: Custom, not needed
  - **影响**: 无（未被调用）
  - **责任人**: 待认领

- [ ] 删除 result_merger.py (73 行)
  - **路径**: `src/olav/agents/result_merger.py`
  - **原因**: Custom, not needed
  - **影响**: 无（未被调用）
  - **责任人**: 待认领

##### 0.4 测试 Inspection Tool
- [ ] 独立测试 inspection.py
  ```bash
  echo '{"action":"list"}' | python3 .olav/tools/inspection.py
  ```
  - **预期**: 返回 JSON，status="success"
  - **责任人**: 待认领
  - **预计时间**: 10 分钟

**PhGit commit 和 tag 创建成功
- ✅ 重构分支创建并推送
- ✅ SQL 注入问题修复且通过测试
- ✅ 死代码全部删除
- ✅ inspection.py 可独立运行py 可独立运行
- ✅ Git 分支创建并推送

---

### Phase 1: 工具重构（3-5 天）

**目标**: 重构工具文件，实现 Admin CLI，创建新 Agent

**计划开始**: 2026-02-16  
**预计耗时**: 3-5 天  
**当前状态**: ⏳ 待开始

#### 任务清单

##### 1.1 工具目录迁移
- [ ] 移动 `.olav/shared/tools/` → `.olav/tools/`
  ```bash
  mv .olav/shared/tools/* .olav/tools/
  rmdir .olav/shared/tools/
  ```
  - **责任人**: 待认领
  - **预计时间**: 5 分钟

##### 1.2 工具合并重构
- [ ] 创建 `.olav/tools/database.py`（合并 smart_sql_query.py）
  - **源文件**: `.olav/shared/tools/smart_sql_query.py` (312 行)
  - **目标**: 简化为 ~280 行
  - **功能**: 保持 schema-aware SQL 查询
  - **测试**: `echo '{"query":"SELECT COUNT(*) FROM devices"}' | python3 .olav/tools/database.py`
  - **责任人**: 待认领
  - **预计时间**: 2 小时

- [ ] 创建 `.olav/tools/network.py`（合并 nornir + list_devices）
  - **源文件**: 
    - `nornir_execute.py` (244 行)
    - `list_devices.py` (203 行)
  - **目标**: 合并为 ~320 行
  - **功能**: 
    - execute_command(device, command)
    - list_devices(filter)
  - **测试**: `echo '{"action":"list"}' | python3 .olav/tools/network.py`
  - **责任人**: 待认领
  - **预计时间**: 3 小时

##### 1.3 删除冗余工具
- [ ] 删除 query_database.py
  - **原因**: 功能已在 database.py
  - **责任人**: 待认领

- [ ] 删除 inspect_schema.py
  - **原因**: schema cache 在 database.py
  - **责任人**: 待认领

- [ ] 删除 discover_data.py
  - **原因**: 功能已在 database.py
  - **责任人**: 待认领

##### 1.4 Admin CLI 实现
- [ ] 创建 `src/olav/cli/admin.py`
  - **命令列表**:
    - `olav admin backup`
    - `olav admin restore <timestamp>`
    - `olav admin status`
    - `olav admin skills`
    - `olav admin schedule <workflow> <cron>`
    - `olav admin inspect run`
    - `olav admin inspect status`
    - `olav admin inspect list`
    - `olav admin inspect logs`
  - **责任人**: 待认领
  - **预计时间**: 4 小时

- [ ] 创建 `src/olav/lib/admin.py`（工具函数库）
  - **函数**: backup_config, restore_config, get_system_status
  - **责任人**: 待认领
  - **预计时间**: 2 小时

##### 1.5 新 Agent 创建
- [ ] 创建 `src/olav/agents/agent.py`
  - **功能**: 
    - 动态加载 `.olav/tools/` 中的所有工具
    - Skills 热加载机制
    - 集成 DuckDBSaver checkpoint
  - **参考**: DEEPAGENTS_SIMPLIFICATION_PLAN.md 11.1 节
  - **责任人**: 待认领
  - **预计时间**: 4 小时

- [ ] 更新 `.olav/AGENTS.md`（注册工具）
  - **添加**: database.py, network.py, inspection.py
  - **责任人**: 待认领
  - **预计时间**: 30 分钟

##### 1.6 测试
- [ ] 单元测试工具
  ```bash
  pytest tests/unit/test_tools.py -v
  ```
  - **责任人**: 待认领
  - **预计时间**: 2 小时

- [ ] E2E 测试 Admin CLI
  ```bash
  olav admin status
  olav admin inspect list
  ```
  - **责任人**: 待认领
  - **预计时间**: 1 小时

**Phase 1 完成标准**:
- ✅ 工具文件从 6 个减少到 3 个（+1 inspection）
- ✅ 代码行数从 1,376 减少到 620
- ✅ Admin CLI 9 个命令全部可用且 < 1 秒
- ✅ 新 Agent 可以加载工具并执行简单查询
- ✅ 单元测试覆盖率 > 80%

---

### Phase 2: 数据库整合（1 天）

**目标**: 合并数据库，创建新数据库文件

**计划开始**: 2026-02-21  
**预计耗时**: 1 天  
**当前状态**: ⏳ 待开始

#### 任务清单

##### 2.1 数据库合并
- [ ] 运行合并脚本
  ```bash
  uv run python scripts/merge_databases.py
  ```
  - **源**: `.olav/db/network.duckdb` (47MB)
  - **目标**: `.olav/db/main.duckdb` (12KB → ~47MB)
  - **备份**: 自动创建 `network.duckdb.backup`
  - **责任人**: 待认领
  - **预计时间**: 30 分钟

- [ ] 验证合并结果
  ```bash
  uv run python -c "
  import duckdb
  conn = duckdb.connect('.olav/db/main.duckdb')
  tables = conn.execute('SHOW TABLES').fetchall()
  print(f'Total tables: {len(tables)}')
  for t in tables:
      count = conn.execute(f'SELECT COUNT(*) FROM {t[0]}').fetchone()[0]
      print(f'{t[0]}: {count} rows')
  "
  ```
  - **责任人**: 待认领
  - **预计时间**: 10 分钟

##### 2.2 创建新数据库
- [ ] 创建 agent.duckdb（Agent 状态持久化）
  ```bash
  uv run python -c "
  import duckdb
  conn = duckdb.connect('.olav/db/agent.duckdb')
  conn.execute('CREATE TABLE checkpoints (thread_id TEXT, checkpoint_id TEXT, data BLOB)')
  conn.close()
  "
  ```
  - **责任人**: 待认领
  - **预计时间**: 10 分钟

- [ ] 创建 llm_cache.db（LLM 响应缓存）
  ```bash
  uv run python -c "
  from langchain_community.cache import SQLiteCache
  from langchain.globals import set_llm_cache
  cache = SQLiteCache(database_path='.olav/db/llm_cache.db')
  "
  ```
  - **责任人**: 待认领
  - **预计时间**: 10 分钟

##### 2.3 更新配置
- [ ] 更新 `config/paths.py`
  ```python
  DB_MAIN_PATH = OLAV_DIR / "db" / "main.duckdb"  # 已存在
  DB_AGENT_PATH = OLAV_DIR / "db" / "agent.duckdb"  # 新增
  DB_LLM_CACHE_PATH = OLAV_DIR / "db" / "llm_cache.db"  # 新增
  ```
  - **责任人**: 待认领
  - **预计时间**: 15 分钟

##### 2.4 测试数据访问
- [ ] 测试 SQL 查询
  ```bash
  uv run olav ask "有多少个设备？"
  ```
  - **预期**: 返回设备数量，使用 main.duckdb
  - **责任人**: 待认领
  - **预计时间**: 10 分钟

**Phase 2 完成标准**:
- ✅ network.duckdb 数据完整迁移到 main.duckdb
- ✅ agent.duckdb 和 llm_cache.db 创建成功
- ✅ 查询功能正常（10 个功能场景验证）
- ✅ 备份文件存在且可恢复

---

### Phase 3: Agent 切换（2 天）

**目标**: 切换到新 Agent，废弃旧路由

**计划开始**: 2026-02-23  
**预计耗时**: 2 天  
**当前状态**: ⏳ 待开始

#### 任务清单

##### 3.1 Agent 集成
- [ ] 更新 `src/olav/cli/main.py`
  ```python
  from olav.agents.agent import create_agent  # 新
  # 删除: from olav.core.orchestrator import orchestrate_query
  
  agent = create_agent()
  result = agent.invoke({"input": user_query})
  ```
  - **责任人**: 待认领
  - **预计时间**: 1 小时

- [ ] 集成 Skills 加载
  - **位置**: `src/olav/agents/agent.py`
  - **功能**: 根据用户查询加载相关 Skill
  - **参考**: DEEPAGENTS_SIMPLIFICATION_PLAN.md 5.3 节
  - **责任人**: 待认领
  - **预计时间**: 3 小时

##### 3.2 删除旧代码
- [ ] 删除 `src/olav/core/orchestrator.py` (1,077 行)
  - **原因**: 正则路由已废弃
  - **影响**: 全部功能由新 Agent 接管
  - **责任人**: 待认领
  - **预计时间**: 10 分钟

- [ ] 删除旧 SubAgent 文件
  - `src/olav/agents/query_agent.py`
  - `src/olav/agents/cli_agent.py`
  - `src/olav/agents/expert_agent.py`
  - `src/olav/agents/inspector_agent.py`
  - `src/olav/agents/admin_agent.py`（保留作为 Skill）
  - **责任人**: 待认领
  - **预计时间**: 15 分钟

##### 3.3 Skills 迁移
- [ ] 保留 `.olav/skills/olav-admin/`
  - **原因**: 对话式管理 + 架构文档访问
  - **无需修改**

- [ ] 创建 `.olav/skills/network-query/SKILL.md`
  - **内容**: 从旧 query_agent.py 提取操作指南
  - **责任人**: 待认领
  - **预计时间**: 2 小时

- [ ] 创建 `.olav/skills/network-cli/SKILL.md`
  - **内容**: 从旧 cli_agent.py 提取操作指南
  - **责任人**: 待认领
  - **预计时间**: 2 小时

- [ ] 删除废弃 Skills
  - `.olav/skills/olav-guard/`
  - `.olav/skills/olav-orchestrator/`
  - `.olav/skills/agent-router/`
  - **责任人**: 待认领
  - **预计时间**: 5 分钟

##### 3.4 E2E 测试
- [ ] 测试 10 个功能场景
  ```bash
  uv run pytest tests/e2e/test_real_scenarios.py -v
  ```
  - **场景列表**: 
    1. 设备数量查询
    2. CSV 导出
    3. 健康检查
    4. OSPF 状态查询（Fallback）
    5. 专家分析
    6. 命令学习
    7. 备份配置
    8. Skill 创建
    9. 定时检查
    10. 架构查询
  - **责任人**: 待认领
  - **预计时间**: 3 小时

**Phase 3 完成标准**:
- ✅ 新 Agent 接管所有查询
- ✅ 旧路由代码全部删除（1,077 行）
- ✅ 10 个功能场景全部通过
- ✅ 响应时间 < 5 秒（原 8-15 秒）
- ✅ Skills 正确加载和卸载

---

### Phase 4: 验收与优化（1-2 天）

**目标**: 全面测试，性能优化，文档更新

**计划开始**: 2026-02-26  
**预计耗时**: 1-2 天  
**当前状态**: ⏳ 待开始

#### 任务清单

##### 4.1 性能测试
- [ ] 响应时间基准测试
  ```bash
  uv run pytest tests/performance/ -v
  ```
  - **目标**: 平均响应时间 < 5 秒
  - **责任人**: 待认领

- [ ] 并发测试
  ```bash
  uv run pytest tests/load/ -v --workers 10
  ```
  - **目标**: 支持 10 并发查询
  - **责任人**: 待认领

##### 4.2 代码质量
- [ ] Ruff 检查
  ```bash
  uv run ruff check src/ --fix
  uv run ruff format src/
  ```
  - **责任人**: 待认领

- [ ] Pyright 类型检查
  ```bash
  uv run pyright src/
  ```
  - **目标**: 0 errors
  - **责任人**: 待认领

##### 4.3 文档更新
- [ ] 更新 README.md
  - **添加**: v2.0 架构说明
  - **责任人**: 待认领

- [ ] 更新 docs/reference/ARCHITECTURE.md
  - **同步**: DEEPAGENTS_SIMPLIFICATION_PLAN 内容
  - **责任人**: 待认领

- [ ] 创建 CHANGELOG.md
  - **内容**: v0.11 → v2.0 变更日志
  - **责任人**: 待认领

##### 4.4 清理工作
- [ ] 删除 `.olav/cache/`
  - **责任人**: 待认领

- [ ] 删除 `.olav/tasks/scheduled/`（175 YAML）
  - **责任人**: 待认领

- [ ] 归档 scripts/daily_inspection.sh（已废弃）
  - **移动到**: `_legacy_archived/scripts/`
  - **责任人**: 待认领

**Phase 4 完成标准**:
- ✅ 测试覆盖率 > 80%
- ✅ 10 个功能场景 100% 通过
- ✅ 响应时间 < 5 秒
- ✅ 代码质量检查全部通过
- ✅ 文档全部更新

---

## 🚨 风险与阻塞项

### 当前阻塞项（0 个）
暂无

### 已识别风险

| 风险 | 等级 | 影响 | 缓解措施 | 责任人 | 状态 |
|------|------|------|---------|--------|------|
| Phase 1 工具重构耗时超预期 | 中 | 延期 2-3 天 | TDD 开发，拆分任务 | - | 🟡 监控中 |
| 数据库合并失败 | 高 | 数据丢失 | 自动备份，验证脚本 | - | 🟢 已缓解 |
| Skills 加载机制复杂 | 中 | 开发延期 | 参考 DeepAgents 示例 | - | 🟡 监控中 |
| E2E 测试失败率高 | 中 | 质量问题 | 每阶段增量测试 | - | 🟢 已缓解 |
| Team 成员不熟悉 DeepAgents | 低 | 学习曲线 | 提供文档和示例 | - | 🟢 已缓解 |

---

## 📈 代码统计

### 当前代码行数（v0.11）
```
src/olav/                    15,200 行
├── agents/                   3,450 行 (5 SubAgents + orchestrator)
├── core/                     2,100 行 (optimizer, enhancer, etc.)
├── tools/                        0 行 (在 .olav/shared/tools/)
└── api/                      1,200 行

.olav/shared/tools/           1,376 行 (6 tools)
tests/                        8,500 行
```

### 目标代码行数（v2.0）
```
src/olav/                     9,800 行 (-35%)
├── agents/                     600 行 (1 Agent) [-83%]
├── core/                       900 行 [-57%]
├── lib/                        500 行 (admin utils)
└── api/                      1,200 行 [不变]

.olav/tools/                    620 行 (3 tools) [-55%]
tests/                       10,000 行 (+18%, coverage ↑)
```

**总减少**: ~6,500 行（-29%）

---

## ✅ 验收标准

### 功能验收（10 个场景）

| # | 场景 | 测试命令 | 预期结果 | 状态 |
|---|------|---------|---------|------|
| 1 | 设备数量查询 | `olav ask "有多少个设备？"` | 返回准确数量 | ⏳ |
| 2 | CSV 导出 | `olav ask "导出设备列表到 CSV"` | 生成 CSV 文件 | ⏳ |
| 3 | 健康检查 | `olav ask "检查网络健康状况"` | 返回健康报告 | ⏳ |
| 4 | OSPF Fallback | `olav ask "查询 OSPF 状态"` | 先查 DB，不足则执行 CLI | ⏳ |
| 5 | 专家分析 | `olav ask "分析 BGP 配置优化建议"` | 返回专家级建议 | ⏳ |
| 6 | 命令学习 | `/learn ntp` | 添加到命令库 | ⏳ |
| 7 | 备份配置 | `olav admin backup` | 创建备份文件 < 1s | ⏳ |
| 8 | Skill 创建 | 对话式创建 Skill | 生成 SKILL.md | ⏳ |
| 9 | 定时检查 | `olav admin schedule ...` | Cron 任务创建 | ⏳ |
| 10 | 架构查询 | `olav ask "OLAV 的架构是什么？"` | 访问文档返回 | ⏳ |

### 性能验收

| 指标 | 当前 (v0.11) | 目标 (v2.0) | 状态 |
|------|-------------|------------|------|
| 平均响应时间 | 8-15 秒 | < 5 秒 | ⏳ |
| 首次查询（冷启动） | 15-20 秒 | < 8 秒 | ⏳ |
| 后续查询（缓存） | 3-5 秒 | < 2 秒 | ⏳ |
| 并发查询支持 | 受限 | 10+ | ⏳ |
| Schema cache 命中率 | ~60% | > 90% | ⏳ |

### 代码质量验收

| 指标 | 目标 | 状态 |
|------|------|------|
| 测试覆盖率 | > 80% | ⏳ |
| E2E 测试通过率 | 100% | ⏳ |
| Ruff 检查 | 0 errors | ⏳ |
| Pyright 类型检查 | 0 errors | ⏳ |
| 死代码 | 0 行 | ⏳ |
| 安全漏洞 | 0 个 | ⏳ |

---

## 📊 每日更新日志

### 2026-02-14 (Day 1)
**完成**:
- ✅ 完成代码审计（67 文件）
- ✅ 完成架构设计（v2.0）
- ✅ 完成 5 个设计文档
- ✅ 创建 inspection.py tool
- ✅ 创建文档索引（INDEX.md）
- ✅ 创建追踪文档（本文档）

**计划**:
- ⏳ 明天开始 Phase 0

**问题**:
- 无

---

### 2026-02-15 (Day 2)
**计划**:
- Phase 0: 备份、清理、测试

**实际**:
- （待更新）

**问题**:
- （待更新）

---

## 📞 联系与协作

### 每日站会
- **时间**: 每天 10:00
- **时长**: 15 分钟
- **议题**: 昨日进展、今日计划、阻塞项

### 代码审查
- **要求**: 所有 PR 必须经过 Review
- **审查者**: 1+ Team member
- **标准**: 遵循 DEEPAGENTS_SIMPLIFICATION_PLAN.md 设计

### 问题上报
- **轻微问题**: 在本文档添加到"风险与阻塞项"
- **严重问题**: 立即通知 Team，暂停实施

---

## 🎓 学习资源

- **DeepAgents 文档**: [deepagents/README.md](../lib/deepagents/README.md)
- **LangGraph 文档**: https://langchain-ai.github.io/langgraph/
- **DuckDB 文档**: https://duckdb.org/docs/
- **OLAV 架构**: [INDEX.md](INDEX.md) → 按顺序阅读

---

**最后更新**: 2026-02-14 23:00  
**更新者**: OLAV Team  
**下次更新**: 2026-02-15 18:00
