# OLAV 新增命令和E2E测试指南

本文档回答用户提出的三个问题，并提供使用指南。

---

## 📋 问题回答

### 问题1: 是否有命令执行snapshot，初始化数据库并检查成功？

**答案**: ✅ 已增强！

#### 新增功能：`olav snapshot --diagnose`

```bash
# 基本用法（包含诊断）
uv run olav snapshot

# 只采集特定设备
uv run olav snapshot --devices R1,R2

# 跳过诊断信息
uv run olav snapshot --no-diagnose
```

#### 诊断信息包含

**Pre-flight 检查**（执行前）:
- ✅ 数据库连接状态（设备数量）
- ✅ LLM API可用性（provider/model/key）
- ✅ Nornir inventory配置（主机数量）
- ✅ 网络设备可达性（采样前3台）

**Post-snapshot 状态**（执行后）:
- ✅ Raw outputs记录数
- ✅ 数据库视图初始化状态
- ✅ 提示下一步操作

#### 示例输出

```
🔍 Running pre-flight diagnostics...
  ✅ Database: Connected (6 devices registered)
  ✅ LLM API: openai/x-ai/grok-4.1-fast
  ✅ Nornir: 6 hosts configured
  ✅ Network: 3/3 sample devices reachable

[执行snapshot...]

📊 Post-snapshot status:
  📝 Raw outputs: 120 records
  📈 Database views: 5 initialized
  
✅ Snapshot Complete
```

#### 失败诊断

如果snapshot失败，会显示具体的故障排除建议：

**连接失败**:
```
❌ Snapshot Error: Connection timeout

💡 Troubleshooting:
  • Check device IP addresses in inventory
  • Verify SSH credentials
  • Ensure network connectivity (VPN if needed)
```

**API失败**:
```
❌ Snapshot Error: API key invalid

💡 Troubleshooting:
  • Check LLM_API_KEY in .env
  • Verify API provider is accessible
```

---

### 问题2: 是否有命令清理所有数据库和缓存？

**答案**: ✅ 已实现！

#### 新增命令：`olav clean`

```bash
# 显示帮助
uv run olav clean

# 清理缓存（查询缓存）
uv run olav clean --cache --force

# 清理checkpoints（会话历史）
uv run olav clean --checkpoints --force

# 清理快照数据（保留devices表）
uv run olav clean --databases --force

# 清理所有内容
uv run olav clean --all --force

# 交互式确认（不加--force）
uv run olav clean --all
```

#### 清理范围

| 选项 | 清理内容 | 保留内容 |
|------|---------|---------|
| `--cache` | `.olav/cache/*.db`<br>查询结果缓存 | 其他所有 |
| `--checkpoints` | `.olav/user_checkpoint.db`<br>`.olav/.last_thread_id`<br>会话历史 | 其他所有 |
| `--databases` | `raw_outputs` 表<br>所有视图（v_*） | `devices` 表<br>（设备清单） |
| `--all` | 以上所有 | `devices` 表 |

#### 安全确认

不加`--force`时会要求确认：

```bash
$ uv run olav clean --all

⚠️  The following will be deleted:
  • Query cache (.olav/cache/*.db)
  • Session checkpoints (.olav/user_checkpoint.db, .olav/.last_thread_id)
  • Snapshot databases (raw_outputs, views - keeps devices table)

Are you sure you want to continue? [y/N]: 
```

#### 示例输出

```bash
$ uv run olav clean --cache --force

🧹 Cleaning...

  ✅ Deleted: .olav/cache/query_result_cache.db
  ✅ Deleted: .olav/cache/semantic_cache.db
  ✅ Cache cleaned

✅ Cleanup complete!
```

---

### 问题3: E2E测试是否应该用真实CLI命令？

**答案**: ✅ 已创建！

#### 新增脚本：`tests/e2e/test_cli_real.sh`

这个脚本完全模拟真实用户CLI操作，而不是调用Python API。

#### 测试阶段

1. **Phase 0**: Pre-flight Checks
   - `olav doctor` - 系统健康检查
   - `olav clean` - 清理环境

2. **Phase 1**: Basic CLI Commands
   - `olav version` - 版本信息
   - `olav --help` - 帮助文档
   - `olav devices` - 设备列表

3. **Phase 2**: Query Commands (无checkpoint)
   - `olav query 'list devices'`
   - `olav query 'list ip addresses on R2'`
   - `olav query 'show R1 BGP neighbors'`

4. **Phase 3**: Interactive Session (有checkpoint)
   - Session 1: `olav --thread-id <id>` - 查询R1
   - Session 2: `olav --thread-id <id>` - 测试记忆（"what did I ask before?"）
   - Session 3: `olav --resume` - 测试恢复

5. **Phase 4**: Data Snapshot
   - `olav snapshot --devices R1,R2` - 含诊断信息

6. **Phase 5**: Post-Snapshot Queries
   - 检查视图是否创建
   - 测试SQL vs CLI fallback

7. **Phase 6**: Cache Behavior
   - 首次查询（慢）
   - 重复查询（快，缓存命中）
   - 验证加速比

8. **Phase 7**: Cleanup Commands
   - `olav clean --cache --force`
   - `olav clean --checkpoints --force`
   - 验证文件已删除

9. **Phase 8**: Error Handling
   - 无效查询
   - 不存在的设备

#### 运行测试

```bash
# 完整测试（8个阶段）
./tests/e2e/test_cli_real.sh

# 预期输出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  OLAV E2E Test - Real CLI Simulation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

═══════════════════════════════════════════════════════════
Phase 0: Pre-flight Checks
═══════════════════════════════════════════════════════════

▶ Running: System health check
  Command: uv run olav doctor
✅ PASS: System health check

...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Test Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tests Passed: 28
Tests Failed: 0

🎉 All tests passed!
```

#### 与Python API测试的对比

| 特性 | Python API测试 | 真实CLI测试 |
|------|--------------|-----------|
| **速度** | 快（直接调用） | 慢（启动开销） |
| **真实性** | 低（绕过CLI层） | 高（完整流程） |
| **错误覆盖** | 只测试Agent逻辑 | 测试CLI+Agent+输出 |
| **Checkpoint** | 难以测试 | 完整测试 |
| **用户体验** | 不测试 | 完整测试 |

**结论**: 两种测试都需要，但CLI测试更接近生产环境。

---

## 🆕 新增命令：`olav doctor`

系统健康检查工具，一次性显示所有状态。

```bash
uv run olav doctor
```

### 输出示例

```
🏥 OLAV System Health Check

1. Database Status
  ✅ Devices table: 6 devices
  ✅ Raw outputs: 120 records
  ✅ Views: 5 initialized (v_interfaces, v_routes, v_bgp_neighbors...)

2. LLM API Configuration
  Provider: openai
  Model: x-ai/grok-4.1-fast
  Base URL: https://openrouter.ai/api/v1
  API Key: ✅ Set
  ✅ LLM API: Ready

3. Nornir Inventory
  ✅ Hosts: 6
  ✅ Groups: 7
     • R1: 192.168.100.101
     • R2: 192.168.100.102
     • R3: 192.168.100.103

4. Network Connectivity
  ✅ Reachable: R1, R2, R3, R4, SW1
  ⚠️  Unreachable: SW2
     Check: VPN, firewall, SSH service

5. Cache & Checkpoints
  ✅ Cache: 3 files (1.2 MB)
  ✅ Checkpoint: 0.8 MB
  ✅ Last session: a7f3d9e2-1b4c...

✅ Health check complete!
```

### 使用场景

- 🔧 **故障排查**: 快速定位问题（数据库/API/网络）
- ✅ **部署验证**: 确认环境配置正确
- 📊 **状态监控**: 检查缓存大小、会话状态
- 🚀 **CI/CD**: 自动化健康检查

---

## 📝 命令速查表

| 命令 | 用途 | 示例 |
|------|------|------|
| `olav doctor` | 系统健康检查 | `uv run olav doctor` |
| `olav snapshot` | 采集数据（含诊断） | `uv run olav snapshot` |
| `olav clean` | 清理数据库/缓存 | `uv run olav clean --all` |
| `olav --thread-id` | 指定会话ID | `uv run olav --thread-id abc123` |
| `olav --resume` | 恢复上次会话 | `uv run olav --resume` |

---

## 🔄 典型工作流

### 1. 首次部署

```bash
# 检查系统状态
uv run olav doctor

# 采集网络数据
uv run olav snapshot

# 验证数据
uv run olav query "list devices"
```

### 2. 日常使用

```bash
# 进入交互模式
uv run olav

# 或单次查询
uv run olav query "show interfaces on R1"

# 恢复之前的对话
uv run olav --resume
```

### 3. 故障排查

```bash
# 运行健康检查
uv run olav doctor

# 清理缓存（解决缓存问题）
uv run olav clean --cache --force

# 重新采集数据
uv run olav snapshot
```

### 4. 测试/开发

```bash
# 清理所有数据
uv run olav clean --all --force

# 运行E2E测试
./tests/e2e/test_cli_real.sh
```

---

## 🎓 最佳实践

### Cache管理

**何时清理缓存**:
- ✅ 修改了agent逻辑或system prompt
- ✅ 发现查询返回过时数据
- ✅ 测试新功能前

**不需要清理**:
- ❌ 正常使用中（缓存加速查询）
- ❌ 只是查看不同数据

### Checkpoint管理

**何时保留**:
- ✅ 需要继续之前的对话
- ✅ 测试别名学习功能
- ✅ 调试会话记忆问题

**何时清理**:
- ✅ 切换到新项目/网络环境
- ✅ 测试初始用户体验
- ✅ 释放磁盘空间

### Snapshot策略

**频率建议**:
- 每日一次（自动化）- 用于历史分析
- 按需采集 - 用于实时诊断
- 变更后采集 - 验证配置更改

---

## 🐛 故障排查

### 问题: snapshot失败

```bash
# 运行doctor检查根因
uv run olav doctor

# 常见原因
# 1. 网络不通 → 检查VPN
# 2. SSH失败 → 检查凭据
# 3. API超时 → 检查LLM_API_KEY
```

### 问题: 查询返回错误数据

```bash
# 清除缓存重试
uv run olav clean --cache --force
uv run olav query "your query here"
```

### 问题: 记忆功能不工作

```bash
# 检查checkpoint是否启用
uv run olav doctor  # 看 "5. Cache & Checkpoints"

# 注意：Orchestrator可能禁用了checkpointer
# 查看 src/olav/agents/orchestrator.py Line 236
```

---

## 📚 相关文档

- `BUG_FIX_QA.md` - Bug修复Q&A
- `test_checkpoint.sh` - Checkpoint功能测试
- `tests/e2e/test_cli_real.sh` - CLI E2E测试

---

**更新日期**: 2026-02-05  
**版本**: OLAV v0.9.6+
