# OLAV 架构重构 v3.2 执行追踪

**Date**: 2026-02-19  
**Target**: OLAVAgent 14 tools → 6 tools；ConfigAgent clean；inspection pipeline ready

---

## 诊断快照（2026-02-19 执行前）

```
OLAVAgent 实际加载（14 个）：
  # 不应该在这里的
  generate_template, read_template_file, save_template,
  search_ntc_templates, execute_command, analyze_output,
  browse_ntc_directory              ← command_learner 的 7 个 SubAgent 工具

  manage_inspection_schedule        ← cron 写操作，应归 ConfigAgent

  # 正确的
  aggregate_inspection_results      ✓
  take_snapshot                     ✓
  search_knowledge                  ✓
  execute_sql                       ✓
  format_and_export                 ✓
  execute_cli                       ✓

  # 未能加载（sync_tools.py 坏 import）
  sync_all, get_sync_age,
  search_sync, diff_configs         ✗ ImportError
```

---

## 任务清单

| # | 任务 | 状态 | 说明 |
|---|------|------|------|
| 1 | 排除 command_learner（agent.py） | ✅ | `_EXCLUDED_SKILLS = {"olav-config", "command_learner", "orchestrator"}` |
| 2 | 迁移 manage_inspection_schedule | ✅ | inspection.py → olav-config/tools/inspection_scheduler.py |
| 3 | 修 sync_tools.py 坏 import | ✅ | 删死导入 get_nornir；scrapli/inspection_views 改 try/except |
| 4 | 接通 thresholds.yaml | ✅ | 路径已正确：`_here.parent / "config" / "thresholds.yaml"`（无需改动） |
| 5 | 清理 inspection SKILL.md | ✅ | 从 tools: 移除 manage_inspection_schedule，加注释说明归属 |
| 6 | 验证工具数量 | ✅ | OLAVAgent 10，ConfigAgent 6（见下方实际输出） |

---

## 验证结果（2026-02-19 执行后）

```
OLAVAgent (10 tools):
  aggregate_inspection_results    ← network-inspection
  take_snapshot                   ← network-snapshot
  diff_configs                    ← network-snapshot (sync_tools 修复后加载)
  get_sync_age                    ← network-snapshot (sync_tools 修复后加载)
  search_sync                     ← network-snapshot (sync_tools 修复后加载)
  sync_all                        ← network-snapshot (sync_tools 修复后加载)
  search_knowledge                ← olav-ops/tools/knowledge_search.py
  execute_sql                     ← olav-ops
  format_and_export               ← olav-ops
  execute_cli                     ← olav-ops

  OLAVAgent skills: network-snapshot, olav-ops, network-inspection

ConfigAgent (6 tools):
  manage_inspection_schedule      ← olav-config/tools/inspection_scheduler.py ✓
  write_file, read_file           ← olav-config
  execute_olav, execute_shell     ← olav-config
  web_search                      ← olav-config

command_learner → 不加载到任何主 Agent（SubAgent 预留）✓
```

**结论**: 目标达成。OLAVAgent 从 14 → 10 工具，4 个 command_learner 工具已排除，manage_inspection_schedule 已迁入 ConfigAgent。

---

## 目标状态

```
OLAVAgent（6 个 inline + 4 个待 sync_tools 修复 = 10 个）：
  execute_sql, execute_cli, format_and_export   ← olav-ops
  search_knowledge                              ← olav-config/tools
  take_snapshot, aggregate_inspection_results  ← network-snapshot, network-inspection
  sync_all, get_sync_age, search_sync,
  diff_configs                                  ← network-snapshot/sync_tools（修后）

ConfigAgent（~6 个）：
  read_file, write_file, execute_shell,
  execute_olav, manage_inspection_schedule,
  index_knowledge_files

command_learner → SubAgent（不加载到任何主 Agent 的 inline tools）
```

---

## 执行日志

| 时间 | 任务 | 结果 |
|------|------|------|
| 2026-02-19 | 创建 tracking 文档 | ✅ |
| 2026-02-19 | agent.py: `_EXCLUDED_SKILLS` 加 command_learner + orchestrator，变量重命名 | ✅ |
| 2026-02-19 | inspection.py 整体移至 olav-config/tools/inspection_scheduler.py | ✅ |
| 2026-02-19 | sync_tools.py: 删死导入 get_nornir，scrapli/inspection_views 改条件式 | ✅ |
| 2026-02-19 | inspection/SKILL.md: tools 列表移除 manage_inspection_schedule | ✅ |
| 2026-02-19 | 验证：OLAVAgent 14→10，ConfigAgent 6，sync_tools 4工具恢复加载 | ✅ |

---

## v3.3 阶段：OLAVAgent → 纯调度器 + DeepAgents SubAgents
**日期**: 2026-02-20  
**目标**: OLAVAgent 自身只持有 format_and_export，通过 `task` tool 分派 SubAgents

### 变更内容

| 文件 | 变更 | 状态 |
|------|------|------|
| `src/olav/agents/agent.py` | 完整重写：LangGraph → `create_deep_agent` + `subagents=[]` | ✅ |
| `.olav/skills/olav-ops/prompts/system.md` | 替换为调度器专用 prompt（原内容保留到 network_ops_subagent.md）| ✅ |
| `.olav/skills/olav-ops/prompts/network_ops_subagent.md` | 新建：network-ops SubAgent prompt（原 system.md 内容）| ✅ |
| `.olav/skills/olav-ops/tools/snapshot_bridge.py` | 删除：功能归入 network-inspection SubAgent 直接加载 | ✅ |
| `dev_docs/AGENT_ARCHITECTURE_v3_2026_02_18.md` | 追加 v3.3 章节 | ✅ |

### 验证结果

```
Orchestrator (1): ['format_and_export']
network-ops (7): ['search_knowledge', 'execute_sql', 'execute_cli',
                  'diff_configs', 'get_sync_age', 'search_sync', 'sync_all']
network-inspection (2): ['take_snapshot', 'aggregate_inspection_results']
ConfigAgent (6): [unchanged]
```

Import test: OK

### LangChain 缓存
`.olav/databases/llm_cache.db` — SQLiteCache，相同查询命中缓存跳过 LLM 调用
