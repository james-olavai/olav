# 🚀 OLAV 测试框架快速参考

## 📋 常见命令速查

### 1️⃣ 查看可用测试

```bash
# 列出所有测试
uv run python tests/test_runner.py --list-tests

# 列出所有组
uv run python tests/test_runner.py --list-groups
```

### 2️⃣ 快速测试 (1 秒)

```bash
uv run python tests/test_runner.py --group quick
```

输出:
```
✅ snapshot_r1 (0.5s)
✅ cli_keywords (0.1s)
✅ fallback_detection (0.1s)
──────────────────
Total: 3 tests, 0.7s
```

### 3️⃣ 缓存验证 (15 秒)

```bash
uv run python tests/test_runner.py --group cache_validation
```

验证:
- ✅ 缓存清理是否完整
- ✅ 冷启动 vs 热启动性能差异
- ✅ FastPath 是否有效

### 4️⃣ 核心功能 (30 秒)

```bash
uv run python tests/test_runner.py --group core
```

测试:
- Snapshot: 所有设备数据拉取
- Query: 基础查询
- Cache: FastPath
- CLI: 关键词检测

### 5️⃣ 完整测试 (60 秒)

```bash
uv run python tests/test_runner.py --group comprehensive
```

### 6️⃣ 扩展功能 (30 秒)

```bash
uv run python tests/01_e2e_extended_test.py
```

新增:
- 真实 CLI echo 交互
- 复杂查询 (JOIN, GROUP BY)
- 缓存污染检测
- 错误处理

---

## 🎯 按需求选择

### 我只想快速验证系统是否工作

```bash
uv run python tests/test_runner.py --group quick
# ⏱️ 1 秒
```

### 我想验证缓存是否真的有效

```bash
uv run python tests/test_runner.py --group cache_validation
# ⏱️ 15 秒
# 结果: cache_hit_validation 会显示真实的 FastPath 性能差异
```

### 我想测试新的查询类型

```bash
uv run python tests/test_runner.py --category query
# ✅ query_basic
# ✅ query_device
# ✅ query_chinese
# ✅ query_all
# + complex_queries (来自扩展框架)
```

### 我想测试特定功能

```bash
# 只测试 Snapshot
uv run python tests/test_runner.py --category snapshot

# 只测试 Fallback
uv run python tests/test_runner.py --test fallback_detection

# 只测试 CLI
uv run python tests/test_runner.py --category cli
```

### 我要做干运行，看命令但不执行

```bash
uv run python tests/test_runner.py --group core --dry-run
```

### 我要快速模式（跳过长测试）

```bash
uv run python tests/test_runner.py --group comprehensive --fast
```

---

## 📊 测试时间对比

| 场景 | 命令 | 时间 | 用途 |
|------|------|------|------|
| **快速** | `--group quick` | 1s | 🔄 CI 快速通过 |
| **缓存检查** | `--group cache_validation` | 15s | ✅ 验证 FastPath |
| **核心** | `--group core` | 30s | 🧪 每日验证 |
| **完整** | `--group comprehensive` | 60s | 🎯 发版前 |
| **扩展** | 01_e2e_extended_test.py | 30s | 🆕 新功能验证 |
| **全量** | 00_e2e_production_test.py | 50s | 📋 完整验收 |

---

## 🔍 FastPath 性能诊断

**问题**: FastPath 性能提升太小？

**诊断步骤**:

```bash
# Step 1: 运行缓存验证
uv run python tests/test_runner.py --group cache_validation

# 观察结果:
# ❌ 如果没有看到性能差异 → 缓存清理不完整
# ✅ 如果看到 >20% 差异 → FastPath 有效
# ⚠️ 如果只有 12% 差异 → 需要优化（Phase 1）
```

**预期结果**:

当前: 12% (冷: 5.94s → 热: 5.22s)
Phase 1 后: 39% (冷: 4.5s → 热: 3.2s)
Phase 2 后: 65% (冷: 2.8s → 热: 1.5s)

---

## 🛠️ 常见问题

### Q1: 测试失败了怎么办？

```bash
# 单独运行该测试，查看详细日志
uv run python tests/test_runner.py --test <test_name> --verbose

# 或查看完整输出
uv run python tests/00_e2e_production_test.py 2>&1 | grep -A 10 "FAIL"
```

### Q2: 想看测试执行的详细步骤？

```bash
# 使用干运行模式
uv run python tests/test_runner.py --group core --dry-run

# 输出显示每个测试的确切命令
```

### Q3: 想在 CI/CD 中快速运行？

```bash
# 使用快速组（最小开销）
uv run python tests/test_runner.py --group quick

# 预计时间: 1 秒
# 覆盖: 核心路径 (Snapshot + CLI + Fallback)
```

### Q4: 想验证新功能是否破坏现有功能？

```bash
# 运行完整测试
uv run python tests/test_runner.py --group comprehensive
```

### Q5: 性能指标在哪里？

```bash
# 查看 JSON 报告
cat E2E_TEST_RESULTS.json | jq .summary
cat EXTENDED_E2E_TEST_RESULTS.json | jq .summary

# 对比缓存快照
cat EXTENDED_E2E_TEST_RESULTS.json | jq .cache_snapshots
```

---

## 📈 性能优化进度追踪

### Phase 1 (本周) - 立即收益

- [ ] 实现 Smart Intent Cache
  ```
  预期收益: 0.2s → 0.01s (-95%)
  验证: uv run python tests/test_runner.py --group cache_validation
  ```

- [ ] 实现 SQL Plan Cache
  ```
  预期收益: 0.8s → 0.1s (-87%)
  验证: uv run python tests/test_runner.py --test cache_fastpath
  ```

### Phase 2 (2 周) - 显著改进

- [ ] 分层 Semantic Cache
- [ ] 流式结果返回

### 验证

```bash
# 比较前后性能
uv run python tests/test_runner.py --group cache_validation

# 预期进度
# Phase 0: 冷 5.94s, 热 5.22s, 差异 12%
# Phase 1: 冷 4.5s,  热 3.2s,  差异 39% ← 2.5x 改善
# Phase 2: 冷 2.8s,  热 1.5s,  差异 65% ← 5.4x 改善
```

---

## 🎯 推荐用法

### 开发阶段

```bash
# 工作前: 快速验证系统
uv run python tests/test_runner.py --group quick

# 修改功能后: 验证相关测试
uv run python tests/test_runner.py --category <modified_category>

# 提交前: 完整验证
uv run python tests/test_runner.py --group comprehensive
```

### CI/CD 流水线

```yaml
# .github/workflows/test.yml
jobs:
  quick-test:
    runs-on: ubuntu-latest
    steps:
      - run: uv run python tests/test_runner.py --group quick  # 1s
      - run: uv run python tests/test_runner.py --group core   # 30s
  
  full-test:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - run: uv run python tests/test_runner.py --group comprehensive  # 60s
```

### 性能基准建立

```bash
# Week 1: 收集基线
for i in {1..5}; do
  uv run python tests/test_runner.py --group cache_validation | grep -E "Cold:|Hot:"
done

# 计算平均值作为基准
```

---

## 💡 Pro Tips

### Tip 1: 快速迭代

```bash
# 修改代码 → 快速测试
alias t-quick='uv run python tests/test_runner.py --group quick'
alias t-cache='uv run python tests/test_runner.py --group cache_validation'

# 然后只需
t-quick    # 1s
t-cache    # 15s
```

### Tip 2: 性能基准

```bash
# 记录当前性能
uv run python tests/test_runner.py --group cache_validation > baseline.txt

# 优化后比较
uv run python tests/test_runner.py --group cache_validation > current.txt
diff baseline.txt current.txt
```

### Tip 3: 监控模式

```bash
# 在屏幕上持续监控
watch -n 10 'uv run python tests/test_runner.py --group quick'
```

### Tip 4: 自动化测试

```bash
# 创建别名
cat >> ~/.bashrc << 'EOF'
e2e-quick() { uv run python tests/test_runner.py --group quick; }
e2e-cache() { uv run python tests/test_runner.py --group cache_validation; }
e2e-full() { uv run python tests/test_runner.py --group comprehensive; }
e2e-list() { uv run python tests/test_runner.py --list-tests; }
EOF

# 使用
e2e-quick
e2e-cache
```

---

## 📚 更多文档

- 🔍 **架构详解**: `docs/E2E_TEST_ARCHITECTURE_AUDIT.md`
- 🚀 **优化方案**: `docs/FASTPATH_OPTIMIZATION_ANALYSIS.md`
- 📊 **完整总结**: `docs/TEST_ARCHITECTURE_IMPROVEMENT_SUMMARY.md`
- 💾 **实现细节**: `tests/01_e2e_extended_test.py`
- ⚙️ **运行器**: `tests/test_runner.py`

---

**最后更新**: 2026-02-02  
**版本**: v1.0  
**状态**: ✅ 生产就绪
