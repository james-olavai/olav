# OLAV v0.9.8 开发者指南 (Developer Guide)

> **版本**: v0.9.8  
> **最后更新**: 2026-01-31  
> **目标读者**: 开发团队成员、新加入的开发者

---

## 🚀 快速开始 (5分钟)

### 1. 理解核心架构 (2分钟)

**OLAV v0.9.8 = K.I.S.S. 原则**

```
用户查询
    ↓
精确匹配缓存 (query_text == ?)
    ↓ (未命中)
Unified Network Expert (ReAct Agent)
    ↓
.olav/skills/network-expert/ (L2-L7)
    ↓
.olav/scripts/*.py (stdin/stdout)
    ↓
缓存结果 + 返回 Markdown
```

**核心决策**:
- ✅ **精确匹配** - 不使用语义搜索/置信度
- ✅ **统一专家** - 单一 `network-expert`（BGP/OSPF/STP/VLAN/ACL/VPN）
- ✅ **零fallback** - Agent自主决策，不硬编码

---

### 2. 环境设置 (2分钟)

```bash
# 克隆仓库
git clone <repo-url>
cd Olav

# 安装依赖（只用 uv，禁止 pip）
uv sync

# 验证安装
uv run olav --version
# 预期: v0.9.8

# 运行测试
uv run pytest tests/00_e2e_acceptance_test.py::TestCodeQuality -v
```

---

### 3. 立即行动 (1分钟)

**当前任务**: Phase 1 代码清理

```bash
# 查看待办清单
cat docs/00_roadmap.md | grep "⏸️"

# 开始第一个任务
cat docs/98_cleanup_checklist.md
```

---

## 📋 核心文档 (开发必读)

### 主文档 (4个)

| 文档 | 用途 | 何时阅读 | 预计时间 |
|:---|:---|:---|:---:|
| **README.md** | 项目概览、架构图 | 第一次 | 5分钟 |
| **docs/00_roadmap.md** | 开发路线图、任务清单 | 每周 | 10分钟 |
| **docs/03_development_spec.md** | 代码规范、质量要求 | 编码前 | 10分钟 |
| **docs/98_cleanup_checklist.md** | 垃圾代码清理清单 | Phase 1 | 15分钟 |

### 参考文档 (2个)

| 文档 | 用途 | 何时阅读 |
|:---|:---|:---|
| **docs/100_audit_report.md** | 架构决策理由、历史问题 | 有疑问时 |
| **.claude/claude.md** | 开发规范、禁止模式 | Agent开发时 |

---

## 🎯 当前开发路线 (v0.9.8)

### Phase 1: 代码清理 (1-2周) ⏸️

**目标**: 删除所有不符合 v0.9.8 架构的代码

#### Task 1.1: 删除置信度代码 ⏸️

```bash
# 删除整个文件
rm src/olav/core/memory_manager.py

# 验证
grep -rn "confidence.*>" src/olav/ | wc -l  # 应为 0
grep -rn "array_cosine_similarity" src/olav/ | wc -l  # 应为 0
```

**详见**: `docs/98_cleanup_checklist.md` § 1

#### Task 1.2: 删除业务fallback ⏸️

```bash
# 修改文件
vim src/olav/core/query_router.py  # 删除 fallback 字段
vim src/olav/agents/orchestrator.py  # 删除 SQL→CLI fallback

# 验证
grep -rn "sql.*fallback.*cli" src/olav/ -i | wc -l  # 应为 0
```

**详见**: `docs/98_cleanup_checklist.md` § 2

#### Task 1.3: 删除Legacy代码 ⏸️

```bash
rm -rf src/olav/analysis/
rm -rf .olav/agent_cache/ (if not used)

# 验证
ls src/olav/analysis/  # 应不存在
```

**详见**: `docs/98_cleanup_checklist.md` § 3

#### Task 1.4: 简化缓存表 ⏸️

```sql
ALTER TABLE commands.main.semantic_cache DROP COLUMN query_embedding;
ALTER TABLE commands.main.semantic_cache DROP COLUMN confidence;
```

**详见**: `docs/98_cleanup_checklist.md` § 2.2

---

### Phase 2: E2E测试 (3-5天) ⏸️

```bash
# 完整测试
uv run pytest tests/00_e2e_acceptance_test.py -v

# 代码质量
uv run ruff check src/ --fix
uv run pyright src/
```

**详见**: `docs/00_roadmap.md` § Phase 2

---

### Phase 3: 文档完善 ✅

**已完成** - 所有核心文档已符合 v0.9.8

---

## 🛠️ 开发工作流

### 日常开发循环

```bash
# 1. 查看当前任务
cat docs/00_roadmap.md | grep "⏸️" | head -1

# 2. 创建分支
git checkout -b task/cleanup-confidence

# 3. 质量检查（编码前）
uv run ruff check src/
uv run pyright src/

# 4. 编写代码
vim src/olav/core/...

# 5. 运行测试
uv run pytest tests/00_e2e_acceptance_test.py::TestCodeQuality -v

# 6. 提交
git add .
git commit -m "cleanup: 删除置信度相关代码"
git push origin task/cleanup-confidence

# 7. PR
# 添加 ArthurClune 为 reviewer
```

---

### 代码质量标准

**必须通过**:

```bash
# 1. Ruff (格式化 + lint)
uv run ruff check src/ --fix
uv run ruff format src/

# 2. Pyright (类型检查)
uv run pyright src/
# 允许 warnings，但 0 errors

# 3. 测试覆盖率 ≥ 80%
uv run pytest --cov=src/olav --cov-fail-under=80

# 4. E2E 测试
uv run pytest tests/00_e2e_acceptance_test.py -v
```

**详见**: `docs/03_development_spec.md`

---

## 🚫 禁止的模式 (CRITICAL)

### 1. 禁止置信度/语义搜索

```python
# ❌ 禁止
array_cosine_similarity(query_embedding, cached_embedding)
if similarity > 0.95: ...

# ✅ 正确
if query_text == cached_query_text: ...
```

### 2. 禁止子专家

```python
# ❌ 禁止
class SwitchingExpert: ...
class RoutingExpert: ...

# ✅ 正确
class NetworkExpert:  # L2-L7 全栈
    """Unified network expert"""
```

### 3. 禁止业务fallback

```python
# ❌ 禁止
try:
    result = execute_sql(query)
except:
    result = execute_cli(query)  # 硬编码fallback

# ✅ 正确 - Agent自主决策
# Agent在ReAct循环中自行选择工具
```

**完整清单**: `.claude/claude.md` § 架构决策

---

## 📚 扩展阅读

### 架构决策记录

**为什么选择精确匹配**？
- 网络运维需要精确性（IP、设备名不容混淆）
- 简化实现，避免置信度调优
- K.I.S.S. 原则

**为什么统一专家**？
- 网络协议紧密耦合（BGP依赖STP状态）
- 避免跨Agent通信开销
- 统一上下文，提升诊断能力

**详见**: `docs/100_audit_report.md` § 0.1-0.4

---

### 历史问题

**曾经存在的问题**（已解决）:
- ❌ v0.8/v0.9/v0.10 版本混乱
- ❌ 文档描述精确匹配，代码用语义搜索
- ❌ 存在switching-expert等子专家
- ❌ 硬编码SQL→CLI fallback

**详见**: `docs/100_audit_report.md` § 0.4

---

## 🎁 快速参考

### 常用命令

```bash
# 开发
uv run olav                              # 启动CLI
uv run olav query "查询R1 BGP状态"        # 单次查询

# 测试
uv run pytest tests/ -v                  # 全部测试
uv run pytest tests/00_e2e_acceptance_test.py::TestPhase5 -v  # 单阶段

# 质量检查
uv run ruff check src/ --fix             # 修复lint
uv run ruff format src/                  # 格式化
uv run pyright src/                      # 类型检查

# 清理
rm src/olav/core/memory_manager.py       # 删除memory manager
rm -rf src/olav/analysis/                # 删除legacy代码
```

---

### 目录结构

```
.
├── .claude/
│   └── claude.md                 # 架构决策、禁止模式
├── .olav/
│   ├── skills/network-expert/    # 统一网络专家
│   └── scripts/*.py              # 工具脚本
├── docs/
│   ├── 00_roadmap.md             # ⭐ 开发路线图
│   ├── 03_development_spec.md    # ⭐ 开发规范
│   ├── 98_cleanup_checklist.md   # ⭐ 清理清单
│   └── 100_audit_report.md       # 架构审计
├── src/olav/
│   ├── agents/                   # Agent实现
│   ├── core/                     # 核心模块
│   └── tools/                    # 工具实现
├── tests/
│   └── 00_e2e_acceptance_test.py # E2E测试
└── README.md                     # ⭐ 项目概览
```

---

### 关键文件

| 文件 | 作用 | 修改频率 |
|:---|:---|:---:|
| `.olav/skills/network-expert/SKILL.md` | 专家定义 | 低 |
| `src/olav/core/unified_database.py` | 缓存查询 | 中 |
| `src/olav/agents/query_agent_v2.py` | 主Agent | 中 |
| `tests/00_e2e_acceptance_test.py` | E2E测试 | 高 |

---

### 验收标准

**Phase 1 完成标准**:

```bash
# 1. 无置信度代码
grep -rn "confidence.*>" src/olav/ | wc -l  # = 0 ✅

# 2. 无业务fallback
grep -rn "sql.*fallback.*cli" src/olav/ -i | wc -l  # = 0 ✅

# 3. 无legacy代码
ls src/olav/analysis/  # 不存在 ✅

# 4. 测试通过
uv run pytest tests/00_e2e_acceptance_test.py -v  # ALL PASSED ✅

# 5. 质量达标
uv run ruff check src/  # 0 errors ✅
uv run pyright src/  # 0 errors ✅
```

---

## 🆘 常见问题

**Q: 从哪里开始**？  
A: 阅读 README.md (5分钟) → 查看 docs/00_roadmap.md → 开始 Phase 1 Task 1.1

**Q: 不确定某个设计是否正确**？  
A: 检查 `.claude/claude.md` § 架构决策 和 `docs/100_audit_report.md`

**Q: 测试失败了怎么办**？  
A: 运行 `uv run pytest <test_file> -v --pdb` 进入调试模式

**Q: 如何添加新功能**？  
A: 先在 `docs/00_roadmap.md` 添加任务 → 遵循 TDD → 更新文档

**Q: PR 需要谁 review**？  
A: 添加 `ArthurClune` 为 reviewer

---

## 📞 联系方式

- **项目维护者**: ArthurClune
- **Issue**: GitHub Issues
- **文档问题**: 修改相应 .md 文件并提 PR

---

**版本**: v0.9.8  
**最后更新**: 2026-01-31  
**下一步**: 开始 Phase 1 Task 1.1 - 删除置信度代码
