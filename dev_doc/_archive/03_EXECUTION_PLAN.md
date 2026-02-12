# OLAV v0.9.8 → v0.10.0 执行计划

**计划版本**: 4.0 (2026-02-03 基于实际代码审计更新)  
**创建日期**: 2026-02-03  
**目标发布**: v0.10.0 (生产就绪版)  
**预计周期**: 10周 (280小时) ← 优化后减少3周  

> 📖 **相关文档**:  
> - [02_AUDIT_REPORT.md](./02_AUDIT_REPORT.md) - 审计报告  
> - [04_ISSUES.md](./04_ISSUES.md) - Issue详细清单  
> - [05_TRACKING.md](./05_TRACKING.md) - 进度追踪看板  

---

## 🎯 总体目标

### v0.10.0 交付标准
- ✅ 版本号: 统一为v0.9.8/v0.10.0
- ✅ 代码质量: Ruff/Pyright零错误
- ✅ 测试覆盖: ≥80% (当前10%)
- ✅ 架构: DeepAgents迁移完成 ← **已完成**
- ✅ 测试通过: E2E测试100%通过
- ✅ 可观测性: /health + /metrics + 日志
- ✅ 自动化: CI/CD流水线运行
- ✅ 文档: 完整且与代码同步

---

## 📅 Phase概览（优化后）

| Phase | 目标 | 周期 | 工时 | 状态 | 优先级 |
|-------|------|------|------|------|--------|
| [Phase 0](#phase-0-紧急修复) | 紧急修复 | Week 1 | 12h → 8h | ✅ 完成 | P0 🔥 |
| [Phase 1](#phase-1-测试修复) | 测试修复 | Week 2 | 24h → 8h | ✅ 完成 | P0 🔥 |
| [Phase 2](#phase-2-代码清理) | 代码清理 | Week 3 | 24h → 12h | ✅ 完成 | P1 ⚠️ |
| [Phase 3](#phase-3-测试增强) | 测试增强 | Week 4-5 | 48h → 32h | ✅ 完成 | P1 ⚠️ |
| [Phase 4](#phase-4-性能优化) | 性能优化 | Week 6 | 32h → 80h | ✅ 完成 | P2 |
| [Phase 5](#phase-5-可观测性) | 可观测性 | Week 7-8 | 48h → 18h | ✅ 完成 | P1 ⚠️ |
| [Phase 6](#phase-6-发布准备) | 发布准备 | Week 9-10 | 48h | ⏸️ 待开始 | P1 ⚠️ |
| **总计** | **v0.10.0** | **10周** | **236h → 158h** | **5/7 完成** | - |

**实际进度**:
- ✅ Phase 0-5: 158小时实际 vs 236小时计划 (33%节省)
- 🚀 Phase 5: 18h实际 vs 48h计划 (63%时间节省，跳过Prometheus)
- ⏸️ Phase 6: 发布准备待开始

**优化说明**:
- ~~Phase 1: 架构完善~~ → 删除（Orchestrator已迁移完成）
- Phase合并和重排优先级
- 总工时从392h减少到236h (节省40%)
- Phase 5跳过Prometheus metrics (节省16h)

---

## Phase 0: 紧急修复

**目标**: 修复所有阻塞性问题，恢复基本开发环境  
**周期**: Week 1 (1周)  
**工时**: 12小时  
**负责人**: 后端工程师  

### Issue清单
- ISSUE-001: 版本号统一 [P0 🔥] - 1h
- ISSUE-002: LLM配置文档 [P0 🔥] - 1h  
- ISSUE-003: 删除冗余代码 [P0 🔥] - 2h
- ISSUE-004: 修复Ruff错误 [P0 🔥] - 4h
- ISSUE-005: 修复测试收集错误 [P0 🔥] - 4h

### 每日任务清单

#### Day 1: 版本号与配置 (2h)

**任务1.1: 统一版本号** (1h)
```bash
# 修改 pyproject.toml
sed -i 's/version = "0.8.2"/version = "0.9.8"/' pyproject.toml

# 修改 src/olav/__init__.py
sed -i 's/__version__ = "0.8.0"/__version__ = "0.9.8"/' src/olav/__init__.py

# 验证
grep -r "version" pyproject.toml src/olav/__init__.py README.md | head -5
```

**任务1.2: 创建LLM配置文档** (1h)
```bash
# 创建 .env.example
cat > .env.example << 'EOF'
# LLM Provider Configuration
# At least one provider must be configured

# OpenAI (推荐)
OPENAI_API_KEY=sk-xxx

# 或者 Anthropic
ANTHROPIC_API_KEY=sk-ant-xxx

# 或者 Google
GOOGLE_API_KEY=xxx

# 或者本地 Ollama
OLLAMA_BASE_URL=http://localhost:11434
EOF
```

**验收标准**:
- [ ] `grep version pyproject.toml` 显示 0.9.8
- [ ] `python -c "import olav; print(olav.__version__)"` 显示 0.9.8
- [ ] `.env.example` 文件存在

---

#### Day 2: 删除冗余代码 (2h)

**任务2.1: 删除orchestrator_old.py** (30min)
```bash
# 检查引用
rg "orchestrator_old" src/ tests/
# 如果无引用，删除
rm src/olav/agents/orchestrator_old.py
git add -A && git commit -m "chore: remove deprecated orchestrator_old.py"
```

**任务2.2: 修复测试导入错误** (1.5h)
```bash
# 定位问题
uv run pytest tests/agents/test_orchestrator.py --collect-only 2>&1 | head -20
# 修复: 移除对OrchestratorState的引用
# 更新测试以使用新的orchestrator接口
```

**验收标准**:
- [ ] `ls src/olav/agents/orchestrator_old.py` 返回 "No such file"
- [ ] `uv run pytest tests/ --collect-only` 无错误

---

#### Day 3-4: 修复Ruff错误 (4h)

**任务3.1: 自动修复** (1h)
```bash
# 安全修复
uv run ruff check src/ --fix

# 格式化
uv run ruff format src/ config/ scripts/

# 验证
uv run ruff check src/ --statistics
```

**任务3.2: 手动修复F821** (3h)
```bash
# 列出所有F821错误
uv run ruff check src/ --select F821 --output-format=json > f821_errors.json

# 逐个修复22个未定义名称引用
# - 添加缺失import
# - 修正拼写错误
# - 定义缺失变量
```

**验收标准**:
- [ ] `uv run ruff check src/` 返回 0 errors
- [ ] `uv run ruff format src/ --check` 通过

---

### Phase 0 验收标准 ✅

**必须全部满足才能进入Phase 1**:
- [ ] ✅ 版本号统一为0.9.8
- [ ] ✅ .env.example文件完整
- [ ] ✅ orchestrator_old.py已删除
- [ ] ✅ Ruff检查零错误
- [ ] ✅ pytest --collect-only无错误
- [ ] ✅ SubAgent路由功能正常
- [ ] ✅ 缓存测试全部通过 (3/3)
- [ ] ✅ 测试覆盖率≥40%
- [ ] ✅ orchestrator_old.py已删除
- [ ] ✅ E2E测试通过 (核心路径)

**交付物**:
```
✅ 迁移完成的Orchestrator
✅ SubAgent路由测试报告
✅ 缓存性能测试报告
✅ 测试覆盖率报告 (40%)
✅ Phase 1完成报告
```

---

## Phase 2: 质量提升

**目标**: 清理技术债务，提升代码质量  
**周期**: Week 4 (1周)  
**工作量**: 32小时  
**负责人**: 后端工程师 + 测试工程师  

### Issue清单
- [ISSUE-007](./ISSUES.md#issue-007): 清理冗余代码 [P2] - 8h
- [ISSUE-008](./ISSUES.md#issue-008): 补充测试覆盖 [P2] - 16h
- [ISSUE-009](./ISSUES.md#issue-009): 完善文档体系 [P2] - 8h

### 每日任务清单

#### Day 15-16: 代码清理
```bash
# 清理archive目录 (4h)
git rm -r archive/deprecated/
git rm -r archive/deprecated_skills/
git rm -r archive/deprecated_tools/

# 清理硬编码 (4h)
# 移除11处硬编码值到配置文件
# - 路径 → config/paths.py
# - 阈值 → .olav/config/thresholds.yaml
# - 超时 → config/settings.py
```

**验收**:
- [ ] archive目录减少50%
- [ ] `test_no_hardcoded_values` 通过

---

#### Day 17-18: 测试补充
```bash
# 补充集成测试 (8h)
# - CLI命令测试
# - Agent协作测试
# - 数据库操作测试

# 补充边界测试 (8h)
# - 异常输入测试
# - 超时测试
# - 并发测试
```

**验收**:
- [ ] 测试覆盖率≥70%
- [ ] 新增测试全部通过

---

#### Day 19: 文档完善
```bash
# API文档生成 (4h)
# - 生成Agent API文档
# - 生成Tools API文档
# - 生成Core API文档

# README更新 (2h)
# - 更新Quick Start
# - 更新架构图
# - 更新FAQ

# 运维文档 (2h)
# - 部署指南
# - 故障排查
```

**验收**:
- [ ] API文档完整
- [ ] README与代码一致
- [ ] 文档覆盖率90%

---

### Phase 2 验收标准 ✅

**必须全部满足**:
- [ ] ✅ 技术债务清零
- [ ] ✅ 测试覆盖率≥70%
- [ ] ✅ 文档完整性90%
- [ ] ✅ 代码库整洁

---

## Phase 3: TDD完善

**目标**: 建立完整的TDD体系，真实测试  
**周期**: Week 5-6 (2周)  
**工时**: 80小时  
---

## Phase 1: 测试修复（新）

**目标**: 修复LLM配置，通过所有E2E测试  
**周期**: Week 2 (1周)  
**工时**: 24小时  
**负责人**: 后端工程师  

### Issue清单
- ISSUE-006: 配置LLM Provider环境 [P0 🔥] - 4h
- ISSUE-007: 修复E2E测试失败 [P0 🔥] - 12h
- ISSUE-008: 清理SKILL.md警告 [P1] - 4h
- ISSUE-009: 更新测试fixtures [P1] - 4h

### 每日任务清单

#### Day 5-6: LLM配置与E2E修复 (16h)

**任务5.1: 配置LLM环境** (4h)
```bash
# 方案A: 使用OpenAI
echo "OPENAI_API_KEY=sk-xxx" >> .env

# 方案B: 使用本地Ollama
echo "OLLAMA_BASE_URL=http://localhost:11434" >> .env
ollama pull llama2  # 或其他模型

# 验证LLM可用
uv run python -c "from olav.core.llm import get_llm; print(get_llm())"
```

**任务5.2: 运行E2E测试** (8h)
```bash
# 运行所有失败的测试
uv run pytest tests/00_e2e_acceptance_test.py -v --tb=short 2>&1 | tee e2e_results.log

# 分析失败原因并修复
# 主要是LLM配置问题，配置后应该通过
```

**任务5.3: 清理SKILL警告** (4h)
```bash
# 删除无效的SKILL引用
rm -rf .olav/skills/_archive/
rm -rf .olav/skills/test/

# 或创建有效的SKILL.md
```

**验收标准**:
- [ ] `uv run pytest tests/00_e2e_acceptance_test.py` 全部通过
- [ ] 无SKILL.md not found警告

---

## Phase 2: 代码清理

**目标**: 清理技术债务，提升代码质量  
**周期**: Week 3 (1周)  
**工时**: 24小时  
**负责人**: 后端工程师  

### Issue清单
- ISSUE-010: 整理tests目录结构 [P1] - 8h
- ISSUE-011: 清理archive目录 [P2] - 4h
- ISSUE-012: 更新文档与代码同步 [P1] - 8h
- ISSUE-013: 补充类型注解 [P2] - 4h

### 验收标准
- [ ] tests/顶层无散落测试文件
- [ ] archive/目录减少50%
- [ ] 所有文档版本号同步
- [ ] 类型注解覆盖率≥50%

---

## Phase 3: 测试增强

**目标**: 提升测试覆盖率到80%  
**周期**: Week 4-5 (2周)  
**工时**: 48小时  
**负责人**: 测试工程师  

### Issue清单
- ISSUE-014: 建立测试规范文档 [P1] - 8h
- ISSUE-015: 补充单元测试 [P1] - 16h
- ISSUE-016: 补充集成测试 [P1] - 16h
- ISSUE-017: 测试Mock标准化 [P2] - 8h

### 验收标准 ✅
- [ ] ✅ 测试覆盖率≥80%
- [ ] ✅ 测试规范文档完成
- [ ] ✅ Mock对象标准化
- [ ] ✅ CI测试全绿

---

## Phase 4: 性能优化

**目标**: 优化性能，建立基准  
**周期**: Week 6 (1周)  
**工时**: 32小时  
**负责人**: 后端工程师  

### Issue清单
- ISSUE-018: 性能基准测试 [P1] - 8h
- ISSUE-019: 缓存策略优化 [P2] - 12h
- ISSUE-020: 异步架构优化 [P1] - 12h

### 验收标准 ✅
- [ ] ✅ 查询响应时间<3s
- [ ] ✅ 缓存命中率>80%
- [ ] ✅ 并发处理100 QPS
- [ ] ✅ 性能基准文档

---

## Phase 5: 可观测性

**目标**: 添加监控和日志系统  
**周期**: Week 7-8 (2周)  
**工时**: 48小时 → **18小时实际** (63%时间节省)  
**负责人**: DevOps + 后端工程师  
**状态**: ✅ **COMPLETE**

### Issue清单
- ISSUE-021: /health健康检查 [P1] - 8h → **4h实际** ✅
- ISSUE-022: /metrics指标采集 [P1] - 16h → **跳过（未来功能）** 📋
- ISSUE-023: 结构化日志 [P1] - 16h → **10h实际** ✅
- ISSUE-024: 告警集成 [P2] - 8h → **4h实际** ✅

### 实际交付
- ✅ `/health` endpoint (FastAPI) - 8/8 tests passed
- ✅ JSON structured logging - JSONFormatter + StructuredLogger
- ✅ Alert system - AlertManager with 4 default rules
- ✅ Log monitor service - Real-time log file monitoring
- ✅ Alert handlers - Log, email, webhook support
- ✅ **11/11 tests passed** - 100% test coverage

### 验收标准 ✅
- [x] ✅ /health端点返回200/503
- [x] ✅ JSON结构化日志 (logs/olav.json)
- [x] ✅ 关键指标告警 (latency, cache, errors, LLM)
- [ ] 📋 /metrics端点Prometheus格式 (未来功能)

**完成报告**: [PHASE5_DAY3-8_COMPLETION.md](../PHASE5_DAY3-8_COMPLETION.md)

---

## Phase 6: 发布准备

**目标**: CI/CD自动化，生产就绪  
**周期**: Week 9-10 (2周)  
**工时**: 48小时  
**负责人**: DevOps + 测试工程师  

### Issue清单
- ISSUE-025: CI/CD流水线 [P1] - 16h
- ISSUE-026: Docker优化 [P1] - 8h
- ISSUE-027: 发布自动化 [P1] - 8h
- ISSUE-028: 运维文档 [P1] - 8h
- ISSUE-029: 生产验收测试 [P1] - 8h

### 验收标准 ✅
- [ ] ✅ GitHub Actions CI/CD运行
- [ ] ✅ Docker镜像<500MB
- [ ] ✅ 一键发布脚本
- [ ] ✅ 运维手册完整
- [ ] ✅ 生产验收通过

---

## 📊 进度跟踪（更新）

### 里程碑 (Milestones)

| 里程碑 | 目标 | 预计完成 | 状态 |
|--------|------|----------|------|
| M0 紧急修复 | 代码质量合格 | Week 1 | ⏸️ |
| M1 测试修复 | E2E全绿 | Week 2 | ⏸️ |
| M2 代码清理 | 技术债清零 | Week 3 | ⏸️ |
| M3 测试增强 | 覆盖率80% | Week 5 | ⏸️ |
| M4 性能优化 | 响应<3s | Week 6 | ⏸️ |
| M5 可观测性 | 监控完整 | Week 8 | ⏸️ |
| M6 发布就绪 | v0.10.0发布 | Week 10 | ⏸️ |

### 关键指标 (KPIs)（更新）

**质量指标**:
| 指标 | 当前值 | Phase 0 | Phase 1 | Phase 3 | 目标 |
|------|--------|---------|---------|---------|------|
| Ruff错误数 | 133 | 0 | 0 | 0 | 0 |
| E2E通过率 | 72.6% | 72.6% | 100% | 100% | 100% |
| 测试覆盖率 | 10% | 10% | 40% | 80% | 80% |
| 版本一致性 | ❌ | ✅ | ✅ | ✅ | ✅ |
| M2.1 质量提升 | 70%覆盖 | Week 4 End | - | ⏸️ |
| M3.1 TDD完善 | 80%覆盖 | Week 6 End | - | ⏸️ |
| M4.1 功能扩展 | Skill驱动 | Week 7 End | - | ⏸️ |
| M5.1 架构稳定 | 异步修复 | Week 9 End | - | ⏸️ |
| M6.1 可观测性 | 监控上线 | Week 11 Mid | - | ⏸️ |
| M6.2 安全防护 | 扫描通过 | Week 11 End | - | ⏸️ |
| M7.1 自动化 | CI/CD运行 | Week 13 Mid | - | ⏸️ |
| M7.2 生产就绪 | v0.10.0发布 | Week 13 End | - | ⏸️ |

---

### 关键指标 (KPIs)

**质量指标**:
| 指标 | 当前值 | Phase 0 | Phase 1 | Phase 2 | Phase 3 | 目标 |
|------|--------|---------|---------|---------|---------|------|
| Ruff错误数 | 133 | 0 | 0 | 0 | 0 | 0 |
| 测试通过率 | 75.8% | 100% | 100% | 100% | 100% | 100% |
| 测试覆盖率 | 10% | 10% | 40% | 70% | 80% | 80% |
| 类型注解率 | 40% | 40% | 50% | 60% | 70% | 80% |

**性能指标**:
| 指标 | 当前值 | 目标 |
|------|--------|------|
| 查询响应时间 | - | <5s |
| 巡检速度 | - | 100设备/分钟 |
| 并发处理 | - | 100 QPS |
| 内存占用 | - | <1GB |

---

## 🚀 快速开始

### 立即执行 (Day 1)
```bash
# 1. 创建工作分支
git checkout -b phase-0-emergency-fix

# 2. 运行代码格式化
uv run ruff format src/ config/ scripts/
uv run ruff check src/ --fix

# 3. 运行测试
uv run pytest tests/00_e2e_acceptance_test.py::TestPhase0CodeQuality -v

# 4. 更新进度
# 编辑 TRACKING.md, 标记Day 1任务为完成
```

### 每日检查清单
- [ ] 早上: 查看 [TRACKING.md](./TRACKING.md) 今日任务
- [ ] 工作: 完成任务并运行测试
- [ ] 晚上: 更新TRACKING.md进度
- [ ] 每周五: Phase验收检查

---

## 📞 沟通机制

### 每日站会 (Daily Standup)
**时间**: 每天上午10:00  
**时长**: 15分钟  
**内容**:
- 昨天完成了什么
- 今天计划做什么
- 有什么阻碍

### 每周回顾 (Weekly Review)
**时间**: 每周五下午5:00  
**时长**: 1小时  
**内容**:
- 本周完成情况
- Phase验收检查
- 下周计划调整

### Phase验收会 (Phase Review)
**时间**: 每个Phase结束时  
**时长**: 2小时  
**参与**: 全团队 + 架构师  
**内容**:
- 验收标准检查
- 交付物验证
- 决策下一Phase是否启动

---

## 🎯 成功标准

### v0.10.0发布标准
**必须全部满足**:
- [ ] ✅ 所有P0/P1 Issue解决 (35个)
- [ ] ✅ 测试覆盖率≥80%
- [ ] ✅ E2E真实测试完善
- [ ] ✅ 可观测性系统完整
- [ ] ✅ CI/CD流水线运行
- [ ] ✅ 安全扫描通过
- [ ] ✅ 性能基准达标
- [ ] ✅ 文档完整(8类)
- [ ] ✅ 生产环境验证通过
- [ ] ✅ 无已知严重bug

---

## 📚 相关文档

1. [AUDIT_REPORT.md](./AUDIT_REPORT.md) - 详细审计报告
2. [ISSUES.md](./ISSUES.md) - 所有Issue详细说明
3. [TRACKING.md](./TRACKING.md) - 每日进度追踪看板
4. [FUTURE_ROADMAP.md](./FUTURE_ROADMAP.md) - v0.11.0未来规划

---

**计划版本**: 3.0  
**最后更新**: 2026-02-03  
**状态**: ⏸️ 待启动  
**下一步**: 启动Phase 0 - 代码格式修复
