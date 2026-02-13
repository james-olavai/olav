# E2E 测试修复计划 & 硬编码配置迁移

**日期**: 2026-02-13  
**状态**: 📋 规划中  
**目标**: 修复 106 个 E2E 测试 + 整理所有硬编码配置

---

## 📊 当前状态概览

| 指标 | 值 | 优先级 |
|-----|-----|--------|
| **总测试数** | 106 | - |
| **通过** | 40 (37.7%) | ✅ |
| **失败** | 56 (52.8%) | 🔴 |
| **错误** | 10 (9.4%) | ❌ |
| **硬编码参数** | ~15+ | 🟡 |

---

## 🔴 优先级 1: 立即修复 (影响最大)

### 1.1 修复 CLI 导出错误 [18个测试]

**问题**: cli/__init__.py 导入不存在的函数

```python
# ❌ 当前 (src/olav/cli/__init__.py:18)
from olav.cli.display import (
    display_banner,
    get_banner,
    load_banner_from_config,
    print_error,        # ❌ 不存在
    print_success,      # ❌ 不存在
    print_welcome,      # ❌ 不存在
)
```

**解决方案**:
- [ ] 检查这些函数是否被使用
- [ ] 如果使用: 在 display.py 中实现
- [ ] 如果不使用: 从 __init__.py 中移除导入

**预期影响**: +18 个测试通过

**时间**: 30 分钟

---

### 1.2 修复模块导入错误 [10个错误]

**问题**: 测试文件导入已删除的模块

**受影响模块**:
- ❌ `olav.integration` (被删除)
- ❌ `olav.agents.orchestrator_v2` (被删除)
- ❌ `olav.core.plan_execution_bridge` (被删除)
- ❌ `olav.core.time_estimation_learner` (被删除)
- ❌ `olav.agents.command_learner_agent` (被删除)

**解决方案**:
- [ ] 更新测试文件中的导入语句指向正确的模块
- [ ] 或删除依赖删除模块的测试

**预期影响**: +10 个测试无错误

**时间**: 1 小时

---

### 1.3 修复 AdminAgent.knowledge_manager 路径问题 [4个测试]

**问题**: AdminAgent.knowledge_manager 的路径结构改变

```python
# ❌ 旧代码
config = agent.config_manager.load_yaml(path)

# ✅ 新代码 (可能)
config = agent.file_manager.load_yaml(path)
```

**解决方案**:
- [ ] 检查 AdminAgent 的新实现
- [ ] 更新测试使用正确的属性/方法
- [ ] 修复路径引用

**受影响测试**: 
- test_knowledge_e2e.py (4个)

**预期影响**: +4 个测试通过

**时间**: 1 小时

---

## 🟡 优先级 2: 中等修复 (中等影响)

### 2.1 修复 QueryAgent 架构问题 [2个测试]

**问题**: QueryAgent 不再有 `backend` 属性

**受影响测试**:
- test_backend_routing.py (2个)

**解决方案**:
- [ ] 调查 QueryAgent 新架构
- [ ] 更新测试以访问正确的属性

**预期影响**: +2 个测试通过

**时间**: 30 分钟

---

### 2.2 修复学习工作流失败 [3个测试]

**问题**: 日志输出或命令解析逻辑改变

**受影响测试**:
- test_learning_workflow.py (3个)

**解决方案**:
- [ ] 更新预期输出
- [ ] 修复模拟数据
- [ ] 调整断言

**预期影响**: +3 个测试通过

**时间**: 45 分钟

---

### 2.3 修复其他架构问题 [22个测试]

**问题**: 多种架构改变导致各种失败

**解决方案**:
- [ ] 逐个分析失败原因
- [ ] 更新过时的测试代码

**预期影响**: +22 个测试通过

**时间**: 2-3 小时

---

## 🟢 硬编码配置迁移计划

### 3.1 识别所有硬编码值

**已扫描的硬编码参数**:

| 文件 | 参数 | 类型 | 当前值 | 建议位置 |
|-----|------|------|--------|---------|
| cache_manager.py | SKILLS_DIR | Path | `.olav/skills` | config/paths.py ✅ |
| admin_agent.py | crontab_file | Path | `.olav/config/crontab` | config/paths.py ✅ |
| database.py | max_output_size | int | 100_000 | ThresholdSettings |
| execution_dispatcher.py | confidence_threshold | float | 0.75 | ExecutionSettings ✅ |
| connection_pool.py | max_size | int | 5 | DatabaseSettings |
| connection_pool.py | timeout_seconds | float | 5.0 | DatabaseSettings |
| session.py | max_length | int | 200 | CacheSettings |
| session.py | threshold_percent | float | 80.0 | CacheSettings |
| api/v1/devices.py | limit | int | 100 | APISettings |
| data_gateway.py | max_age_days | int | 30 | DataGatewaySettings |
| expert_constraints.py | min_score | float | 0.80 | ValidationSettings |
| expert_constraints.py | max_score | float | 1.0 | ValidationSettings |

---

### 3.2 添加缺失的设置类

**需要添加到 config/settings.py**:

```python
class DataGatewaySettings(BaseSettings):
    """Data Gateway Configuration"""
    
    max_age_days: int = Field(
        default=30,
        description="Maximum age of data in days for recommendations"
    )
    limit: int = Field(
        default=5,
        description="Maximum number of results returned by data gateway"
    )


class APISettings(BaseSettings):
    """API Configuration"""
    
    default_limit: int = Field(
        default=100,
        description="Default limit for paginated results"
    )
    max_limit: int = Field(
        default=500,
        description="Maximum allowed limit for paginated results"
    )


class ValidationSettings(BaseSettings):
    """Validation and Scoring Configuration"""
    
    expert_min_score: float = Field(
        default=0.80,
        description="Minimum score threshold for expert analysis"
    )
    expert_max_score: float = Field(
        default=1.0,
        description="Maximum score for expert analysis"
    )
    vague_term_threshold: float = Field(
        default=0.05,
        description="Threshold for detecting vague terms"
    )
```

**时间**: 30 分钟

---

### 3.3 迁移硬编码值

**步骤**:

1. **添加新设置类到 config/settings.py**
   - [ ] DataGatewaySettings
   - [ ] APISettings
   - [ ] ValidationSettings

2. **更新代码导入**
   
   ```python
   # ❌ 旧代码
   MAX_OUTPUT_SIZE = 100_000
   CONFIDENCE_THRESHOLD = 0.75
   
   # ✅ 新代码
   from config.settings import get_settings
   
   settings = get_settings()
   max_output_size = settings.execution.confidence_threshold
   ```

3. **验证所有模块使用新配置**
   - [ ] 检查 database.py
   - [ ] 检查 execution_dispatcher.py
   - [ ] 检查 connection_pool.py
   - [ ] 检查 data_gateway.py
   - [ ] 检查其他使用硬编码值的模块

**预期收益**: 
- ✅ 清除硬编码值
- ✅ 支持环境变量覆盖
- ✅ 更灵活的配置管理

**时间**: 2 小时

---

## 📋 执行清单

### Phase 1: 立即修复 (预计 2.5 小时)

- [ ] **任务 1.1**: 修复 CLI 导出错误 (30分钟)
  - [ ] 检查 print_error, print_success, print_welcome 使用
  - [ ] 在 display.py 中实现或从 __init__.py 中移除

- [ ] **任务 1.2**: 修复模块导入错误 (1小时)
  - [ ] 更新 5 个测试文件中的导入
  - [ ] 验证编译成功

- [ ] **任务 1.3**: 修复 AdminAgent 路径问题 (1小时)
  - [ ] 调查新 API
  - [ ] 更新 4 个测试

### Phase 2: 配置迁移 (预计 3 小时)

- [ ] **任务 2.1**: 审查硬编码扫描结果 (30分钟)
  
- [ ] **任务 2.2**: 添加新设置类 (30分钟)
  - [ ] DataGatewaySettings
  - [ ] APISettings
  - [ ] ValidationSettings

- [ ] **任务 2.3**: 迁移硬编码值 (2小时)
  - [ ] database.py
  - [ ] execution_dispatcher.py
  - [ ] connection_pool.py
  - [ ] data_gateway.py
  - [ ] 其他模块

### Phase 3: 验证 (预计 1 小时)

- [ ] **任务 3.1**: 运行全套 E2E 测试 (30分钟)
  
- [ ] **任务 3.2**: 验证配置加载 (30分钟)
  - [ ] 检查环境变量覆盖
  - [ ] 检查 .olav/settings.json 覆盖

---

## 🎯 预期结果

### 测试通过率提升

```
现状:    37.7% (40/106)
修复P1:  ~62%   (+28个)  ← 优先级1修复
修复P2:  ~70%   (+7个)   ← 优先级2修复
目标:    80%+
```

### 配置现状改善

```
硬编码值:    ~15+
配置驱动:    ~15+
设置类:      13 → 16
环境支持:    ✅ 完整
```

---

## 💾 相关文件

- [E2E_TEST_REPORT.md](E2E_TEST_REPORT.md) - 详细的测试执行报告
- [CODE_SIMPLIFICATION_ROADMAP.md](dev_doc/CODE_SIMPLIFICATION_ROADMAP.md) - 长期优化计划
- [config/settings.py](config/settings.py) - 主配置文件
- [config/paths.py](config/paths.py) - 路径配置

---

## 📝 注意事项

1. **配置优先级** (从高到低):
   - 环境变量 (export VAR=value)
   - .env 文件 (LLM_API_KEY=...)
   - .olav/settings.json ({"key": "value"})
   - settings.py 默认值

2. **向后兼容**:
   - 新配置必须有合理的默认值
   - 现有代码继续运行
   - 逐步迁移，不一次性修改

3. **测试覆盖**:
   - 修改配置后运行 E2E 测试
   - 验证环境变量覆盖
   - 检查 .olav/settings.json 加载

---

**下一步**: 按 Phase 1 → Phase 2 → Phase 3 依次执行

**预计总时间**: 6-8 小时  
**优先级**: 🔴 高 (影响产品功能)  
**关键依赖**: 无
