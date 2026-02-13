# Session 3 修复计划 - 全面修复框架

**日期**: 2026-02-13  
**状态**: 规划中 → 开始执行  
**总任务**: 30+ 个修复项目  
**预期耗时**: 6-8 小时  

---

## 📋 TODO 清单总览

### 🔴 P1：关键修复（必须完成，影响功能）

#### P1.1 CLI/Display 模块导出问题 ⚠️ BLOCKING 18 个测试
- [ ] 确认 `print_error` 在 `display.py` 中的位置
- [ ] 修复 display 模块的导出
- [ ] 验证 CLI 命令执行
- **预期**: 修复 ~18 个测试
- **耗时**: 30 分钟

#### P1.2 修复硬编码配置（23 处）
**提取到 config/settings.py**:
- [ ] 提取 `.olav` 路径配置
- [ ] 提取 `exports` 路径配置  
- [ ] 提取 `timeout` 值配置
- [ ] 提取 `host/port` 配置
- [ ] 更新所有调用点（23处）
- **预期**: 所有路径和参数可配置
- **耗时**: 1.5 小时

#### P1.3 修复模块导入错误（10 处）
- [ ] 扫描所有失败的导入
- [ ] 更新测试文件中的导入语句
- [ ] 验证导入没有其他错误
- **预期**: 修复 10 个收集失败
- **耗时**: 30 分钟

#### P1.4 修复 AdminAgent.knowledge_manager
- [ ] 检查 knowledge_manager 的新路径
- [ ] 更新测试夹具
- [ ] 验证知识库操作
- **预期**: 修复 ~4 个测试
- **耗时**: 45 分钟

### 🟡 P2：中等优先级（应该完成，改进质量）

#### P2.1 修复 QueryAgent 架构
- [ ] 检查 QueryAgent 的 backend 属性
- [ ] 更新测试以匹配新架构
- **预期**: 修复 ~2 个测试
- **耗时**: 1 小时

#### P2.2 修复 display.py 导出的所有函数
- [ ] 检查所有导出的函数
- [ ] 添加缺失的导出
- [ ] 验证导入
- **预期**: 所有CLI相关函数可用
- **耗时**: 45 分钟

#### P2.3 简化错误处理（优选）
- [ ] 扫描无意义的 try-except
- [ ] 删除或改进
- **预期**: -50 到 -100 行
- **耗时**: 1 小时（可选）

### 🟢 P3：低优先级（优化，可后续）

#### P3.1 学习工作流问题
- [ ] 检查日志输出变更
- [ ] 更新预期输出
- **耗时**: 1 小时

#### P3.2 其他架构相关问题
- [ ] 逐个修复剩余问题
- **耗时**: 2-3 小时

---

## 📊 优先级排序

```
P1 (必须完成 - 关键路径):
├─ P1.1 CLI/display 导出        → 30 min   (18 tests)
├─ P1.2 硬编码配置提取           → 1.5 h    (config)
├─ P1.3 模块导入修复             → 30 min   (10 errors)
└─ P1.4 knowledge_manager         → 45 min   (4 tests)

P2 (应该完成 - 改进):
├─ P2.1 QueryAgent 架构           → 1 h      (2 tests)
├─ P2.2 display.py 导出优化      → 45 min   (all exports)
└─ P2.3 错误处理简化（可选）      → 1 h      (cleanup)

P3 (可后续 - 优化):
├─ P3.1 学习工作流               → 1 h      (3 tests)
└─ P3.2 其他问题                 → 2-3 h    (22 tests)

总耗时: 6-8 小时完成 P1+P2, 8-11 小时完成全部
```

---

## 🔧 详细修复步骤

### Step 1: 硬编码配置提取（优先）

**目标**: 将 23 处硬编码配置移到 settings.py

**需要提取的配置**:
```python
# 路径配置
OLAV_CONFIG_DIR = ".olav"
EXPORTS_DIR = "exports"
SKILLS_DIR = ".olav/skills"
KNOWLEDGE_DIR = ".olav/knowledge"

# 超时配置
DEFAULT_TIMEOUT = 30
CLI_TIMEOUT = 300
SCRIPT_ENGINE_TIMEOUT = 300
SESSION_TIMEOUT = 30

# 连接配置
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
NORNIR_HOST = "localhost"

# 业务参数
MAX_RETRIES = 3
BATCH_SIZE = 10
MAX_DEVICES = 1000
```

**修改文件**:
1. `config/settings.py` - 添加新的配置类
2. `23 处` 调用文件 - 替换硬编码为 config.settings.XXX

### Step 2: 修复 display.py 导出

**文件**: `src/olav/cli/display.py`

**问题**: `print_error` 和其他函数没有正确导出

**解决方案**:
```python
# 在 display.py 末尾添加
__all__ = [
    'print_error',      # 修复缺失的导出
    'print_header',
    'print_success',
    'print_warning',
    # ... 其他函数
]
```

### Step 3: 修复模块导入

**问题**: 10 个测试文件有过时的导入

**解决方案**: 更新 import 语句指向正确的模块

**例如**:
```python
# ❌ 旧:
from olav.agents.orchestrator_v2 import ...

# ✅ 新:
from olav.agents.orchestrator import ...
```

### Step 4: 修复知识库路径

**问题**: AdminAgent.knowledge_manager 的路径变更

**解决方案**: 更新到新的路径

---

## ✅ 验证步骤

每个修复完成后的验证:

```bash
# 1. 编译检查
uv run python -m py_compile src/olav/**/*.py

# 2. 导入检查
uv run python -c "from config.settings import *; print('✅ Settings OK')"

# 3. 单个测试
uv run pytest tests/e2e/test_cli_scenarios.py -v

# 4. 全套测试
uv run pytest tests/e2e/ --tb=short -q
```

---

## 📈 预期改进

**修复前**:
- 通过率: 37.7% (40/106)
- 失败: 56
- 错误: 10

**修复后（P1 完成）**:
- 通过率: ~65% (预期 +27%)
- 失败: ~20
- 错误: 0 ✅

**修复后（P1+P2 完成）**:
- 通过率: ~75% (预期 +37%)
- 失败: ~3-5
- 错误: 0 ✅

---

## 🚀 执行时间表

| 时间 | 任务 | 预期完成 |
|------|------|---------|
| 0:00-0:30 | 硬编码配置提取 | settings.py |
| 0:30-1:00 | 更新调用点 (23处) | 全部引用 |
| 1:00-1:30 | display.py 导出修复 | print_error 可用 |
| 1:30-2:00 | 模块导入修复 | 10 errors 消除 |
| 2:00-2:45 | knowledge_manager 修复 | 4 tests 通过 |
| 2:45-3:00 | 验证和编译检查 | 100% 编译 |
| 3:00-3:45 | QueryAgent 架构修复 | 2 tests 通过 |
| 3:45-4:00 | 最终测试运行 | 通过率检查 |

---

## 📝 修复顺序（关键）

**勿乱序**，按以下顺序执行：

1. ✅ 硬编码配置提取（所有文件都依赖这个）
2. ✅ display.py 导出修复（CLI 测试需要）
3. ✅ 模块导入修复（阻止测试收集）
4. ✅ knowledge_manager 修复（数据操作）
5. ⚪ QueryAgent 架构修复（可并行）

---

## 🎯 成功标准

**P1 完成(必须)**:
- ✅ 硬编码配置全部提取到 settings.py
- ✅ CLI display 导出正确
- ✅ 模块导入错误消除
- ✅ knowledge_manager 路径正确
- ✅ 通过率 > 60%

**P2 完成(应该)**:
- ✅ QueryAgent 测试通过
- ✅ 通过率 > 70%
- ✅ display 导出完整

**全部完成(理想)**:
- ✅ 通过率 > 75%
- ✅ 所有关键路径工作

