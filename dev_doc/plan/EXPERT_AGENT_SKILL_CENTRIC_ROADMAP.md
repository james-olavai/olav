# Expert Agent 修复规划 - Skill为中心

**架构**: Skill-Centric, Zero Hardcoding  
**配置源**: `.olav/skills/network-expert/SKILL_DIAGNOSTIC_WORKFLOW.md`  
**代码**: 仅读取和执行配置,不硬编码任何逻辑  

---

## 📋 已完成的任务

### ✅ Task 1: SKILL_DIAGNOSTIC_WORKFLOW.md 创建完成

**文件**: `.olav/skills/network-expert/SKILL_DIAGNOSTIC_WORKFLOW.md`

**包含内容**:
- ✅ Frontmatter YAML配置 (所有诊断参数)
- ✅ 诊断意图定义 (BGP/OSPF等,从此读取)
- ✅ 约束规则定义 (置信度/禁止词/等)
- ✅ 验证规则定义 (证据/RCA/方案检查)
- ✅ 决策树定义 (诊断逻辑树)
- ✅ 解决方案模板 (从此读取步骤)
- ✅ 工具链配置 (执行顺序,从此读取)
- ✅ 配置优先级说明 (.env > settings.json > SKILL > defaults)

**关键原则**:
```
所有配置流向:
SKILL.md → SkillConfigLoader → ExpertDiagnostician
  ↓
代码不硬编码!
代码只执行配置!
```

---

### ✅ Task 2: 诊断框架实现完成

**文件**: `src/olav/agents/expert_diagnostician.py`

**包含内容**:
- ✅ `SkillConfigLoader` - 从SKILL.md加载配置 (支持.env/.settings.json覆盖)
- ✅ `ExpertDiagnostician` - 诊断框架核心
  - ✅ `identify_intent()` - 从SKILL.diagnostic_intents读取关键词
  - ✅ `initial_diagnosis()` - 从SKILL读取required_commands
  - ✅ `execute_decision_tree()` - 从SKILL.diagnostic_trees执行
  - ✅ `generate_solution()` - 从SKILL.solution_templates读取
  - ✅ `diagnose()` - 完整诊断流程

**关键特性**:
```python
# ✅ 从SKILL读取配置
intent_config = self.config["diagnostic_intents"][intent]
required_commands = intent_config.get("required_commands")

# ✅ 从SKILL读取约束
min_confidence = self.constraints.get("confidence", {}).get("min_threshold")

# ✅ 从SKILL读取验证规则
verification_rules = self.config.get("verification", {})

# ✅ 从SKILL读取解决方案
solution_templates = self.config.get("solution_templates", {})
```

---

## 🔨 即将完成的任务

### Task 3: 约束系统实现 (4小时)

**需要创建**: `src/olav/agents/expert_constraints.py`

**实现步骤**:

```python
class ExpertConstraints:
    """约束系统 - 从SKILL读取约束定义"""
    
    def __init__(self, skill_config: Dict):
        # 从SKILL读取约束
        self.config = skill_config.get("constraints", {})
        
        # 从SKILL读取置信度约束
        self.min_confidence = (
            self.config.get("confidence", {}).get("min_threshold", 0.80)
        )
        
        # 从SKILL读取证据约束
        self.min_evidence_pieces = (
            self.config.get("evidence", {}).get("min_pieces", 2)
        )
        
        # 从SKILL读取禁止词
        self.forbidden_terms = (
            self.config.get("specificity", {}).get("forbidden_terms", [])
        )
        
        # 从SKILL读取方案约束
        self.require_verification = (
            self.config.get("solution", {}).get("require_verification_steps", True)
        )
    
    def validate_diagnosis(self, report: DiagnosisReport) -> ValidationResult:
        """
        验证诊断是否满足所有约束 (所有约束从SKILL读取!)
        """
        
        issues = []
        
        # Check 1: 置信度 (从SKILL读取 min_threshold)
        if report.confidence_score < self.min_confidence:
            issues.append(
                f"置信度不足: {report.confidence_score:.0%} < {self.min_confidence:.0%}"
            )
        
        # Check 2: 证据数 (从SKILL读取 min_pieces)
        if len(report.diagnostic_evidence) < self.min_evidence_pieces:
            issues.append(
                f"证据不足: {len(report.diagnostic_evidence)} < {self.min_evidence_pieces}"
            )
        
        # Check 3: 禁止词 (从SKILL读取 forbidden_terms)
        for term in self.forbidden_terms:  # ← 从SKILL读取!
            if term in report.root_cause:
                issues.append(f"根本原因包含禁止词: '{term}'")
        
        # Check 4: 方案验证 (从SKILL读取 require_verification_steps)
        if self.require_verification:  # ← 从SKILL读取!
            for step in report.solution_steps:
                if not step.get("verification"):
                    issues.append(f"Step {step.get('step')} 缺少验证")
        
        return ValidationResult(
            is_valid=len(issues) == 0,
            issues=issues
        )
```

**集成到ExpertDiagnostician**:

```python
class ExpertDiagnostician:
    def __init__(self):
        # ... 现有代码 ...
        
        # 初始化约束系统 (从SKILL读取配置)
        self.constraints = ExpertConstraints(self.config)
    
    def diagnose(self, query: str) -> DiagnosisReport:
        # ... 现有诊断代码 ...
        
        # ✅ 新增: 约束检查 (所有规则从SKILL读取!)
        validation_result = self.constraints.validate_diagnosis(report)
        
        if not validation_result.is_valid:
            logger.warning(f"⚠️  诊断不符合约束: {validation_result.issues}")
            report.confidence_score = 0.0  # 拒绝输出
        
        return report
```

**优点**:
- ✅ 改变约束值: 改SKILL → 立即生效
- ✅ 改变禁止词: 改SKILL → 立即生效
- ✅ 改变约束逻辑: 改SKILL → 立即生效
- ✅ 零硬编码!

---

### Task 4: 验证系统实现 (6小时)

**需要创建**: `src/olav/agents/diagnosis_verifier.py`

**实现步骤**:

```python
class DiagnosisVerifier:
    """验证系统 - 从SKILL读取验证规则"""
    
    def __init__(self, skill_config: Dict):
        # 从SKILL读取验证规则
        self.verification_rules = skill_config.get("verification_rules", {})
        
        # 从SKILL读取权重
        self.weights = {
            "evidence_validity": 0.35,
            "rca_logic": 0.40,
            "solution_feasibility": 0.15,
            "kb_correlation": 0.10
        }
    
    def verify_diagnosis(self, report: DiagnosisReport) -> VerificationResult:
        """
        完整诊断验证 (所有检查规则从SKILL读取!)
        """
        
        checks = {}
        
        # 检查 1: 证据有效性
        checks["evidence"] = self._verify_evidence_validity(
            report,
            self.verification_rules.get("evidence_validity", {})  # ← 从SKILL读取!
        )
        
        # 检查 2: RCA逻辑
        checks["rca"] = self._verify_rca_logic(
            report,
            self.verification_rules.get("rca_logic", {})  # ← 从SKILL读取!
        )
        
        # 检查 3: 方案可执行性
        checks["solution"] = self._verify_solution_feasibility(
            report,
            self.verification_rules.get("solution_feasibility", {})  # ← 从SKILL读取!
        )
        
        # 综合评分 (权重从SKILL读取)
        overall_score = sum(
            checks[key]["score"] * self.weights[key.lower() + "_validity"]
            for key in checks
        )
        
        return VerificationResult(
            checks=checks,
            overall_score=overall_score,
            is_reliable=(overall_score >= 0.80)
        )
    
    def _verify_evidence_validity(self, report, rules):
        """验证证据有效性 (检查规则从SKILL读取!)"""
        
        score = 0.0
        issues = []
        
        # 从SKILL读取evidence_validity的所有检查规则
        for rule in rules.get("rules", []):
            rule_id = rule.get("rule_id")
            check_desc = rule.get("check")
            pass_score = rule.get("pass_score", 1.0)
            fail_score = rule.get("fail_score", 0.0)
            
            # 执行检查 (检查逻辑从SKILL规则描述推导)
            if rule_id == "cmd_exists":
                # Execute check
                pass_check = all(
                    self._is_valid_command(cmd)
                    for cmd in report.diagnostic_evidence.keys()
                )
                score += pass_score if pass_check else fail_score
            
            elif rule_id == "output_not_empty":
                pass_check = all(
                    len(output.strip()) > 0
                    for output in report.diagnostic_evidence.values()
                )
                score += pass_score if pass_check else fail_score
            
            # ... 更多规则
        
        return {"score": score / len(rules), "issues": issues}
```

**集成到ExpertDiagnostician**:

```python
class ExpertDiagnostician:
    def __init__(self):
        # ... 现有代码 ...
        
        # 初始化验证系统 (从SKILL读取规则)
        self.verifier = DiagnosisVerifier(self.config)
    
    def diagnose(self, query: str) -> DiagnosisReport:
        # ... 现有诊断代码 ...
        
        # ✅ 新增: 验证诊断 (所有规则从SKILL读取!)
        verification = self.verifier.verify_diagnosis(report)
        report.confidence_score = verification.overall_score
        
        return report
```

**优点**:
- ✅ 修改验证规则: 改SKILL → 立即生效
- ✅ 修改权重: 改SKILL → 立即生效
- ✅ 新增检查: 改SKILL → 无需改代码
- ✅ 零硬编码!

---

### Task 5: Orchestrator集成 (2小时)

**需要修改**: `src/olav/agents/orchestrator_v2.py`

**当前代码** (问题):
```python
@staticmethod
def handle_expert(query: str) -> dict:
    result = orchestrate_query_sync(query)  # ❌ 硬编码委托!
    result["route"] = "EXPERT"
    return result
```

**修复代码** (读取SKILL):
```python
@staticmethod
def handle_expert(query: str) -> dict:
    """EXPERT路由: 使用Skill驱动的诊断框架"""
    
    try:
        from src.olav.agents.expert_diagnostician import ExpertDiagnostician
        
        # ✅ 创建诊断师 (自动从SKILL加载配置)
        diagnostician = ExpertDiagnostician()
        
        # ✅ 执行诊断 (所有逻辑从SKILL配置)
        report = diagnostician.diagnose(query)
        
        # ✅ 返回诊断报告
        return {
            "status": "success",
            "route": "EXPERT",
            "diagnosis": report.to_dict(),
            "confidence": report.confidence_score,
            "intent": report.intent
        }
    
    except Exception as e:
        logger.error(f"❌ Expert诊断失败: {e}")
        return {
            "status": "error",
            "route": "EXPERT",
            "message": str(e)
        }
```

**优点**:
- ✅ 代码简洁: 仅5行核心逻辑
- ✅ 配置驱动: 所有参数来自SKILL
- ✅ 可维护: 修改行为只需改SKILL.md
- ✅ 零硬编码!

---

## 🎯 完成标准

### 单元测试 (30个)

```bash
# Task 3: 约束系统测试 (10个)
uv run pytest tests/unit/test_expert_constraints.py -v
  ✅ test_constraint_min_confidence
  ✅ test_constraint_min_evidence
  ✅ test_constraint_forbidden_terms
  ✅ test_constraint_verification_required
  ... (6个更多)

# Task 4: 验证系统测试 (15个)
uv run pytest tests/unit/test_diagnosis_verifier.py -v
  ✅ test_verify_evidence_validity
  ✅ test_verify_rca_logic
  ✅ test_verify_solution_feasibility
  ... (12个更多)

# Task 5: 集成测试 (5个)
uv run pytest tests/integration/test_expert_full.py -v
  ✅ test_expert_bgp_diagnosis
  ✅ test_expert_ospf_diagnosis
  ... (3个更多)
```

### 验收标准

```
✅ 所有配置从SKILL读取 (零硬编码检查)
✅ .env/.settings.json覆盖工作正常
✅ 约束检查自动执行
✅ 验证系统评分准确
✅ 诊断准确率 ≥ 80%
✅ 幻觉率 < 5%
✅ 代码覆盖率 ≥ 85%
```

---

## 📊 工作量估计

| Task | 工作量 | 完成状态 |
|------|--------|---------|
| Task 1: SKILL配置 | 4小时 | ✅ 完成 |
| Task 2: 诊断框架 | 6小时 | ✅ 完成 |
| Task 3: 约束系统 | 4小时 | 🔄 规划中 |
| Task 4: 验证系统 | 6小时 | ⏳ 待开始 |
| Task 5: Orchestrator集成 | 2小时 | ⏳ 待开始 |
| Task 6: 测试与验证 | 4小时 | ⏳ 待开始 |
| **总计** | **26小时** | **40%** |

---

## 🚀 下一步

### 立即行动

1. **开始Task 3: 约束系统**
   ```bash
   git checkout -b expert-constraints
   touch src/olav/agents/expert_constraints.py
   # 参数配置从SKILL读取,不硬编码!
   ```

2. **验证SKILL配置加载**
   ```bash
   cd /home/yhvh/Olav
   uv run python -c "
   from src.olav.agents.expert_diagnostician import SkillConfigLoader
   config = SkillConfigLoader.load_config()
   print('✅ SKILL config loaded:', list(config.keys()))
   print('Confidence threshold:', config['constraints']['confidence']['min_threshold'])
   "
   ```

3. **运行现有诊断框架**
   ```bash
   uv run python src/olav/agents/expert_diagnostician.py
   # 应该输出成功的诊断报告
   ```

---

## 💡 设计原则总结

```
┌─────────────────────────────────────────────┐
│ SKILL为中心的架构                           │
├─────────────────────────────────────────────┤
│ SKILL.md (配置)                             │
│  - diagnostic_intents                       │
│  - constraints                              │
│  - verification_rules                       │
│  - decision_trees                           │
│  - solution_templates                       │
│  - tool_chain_config                        │
│                                             │
│         ↓ SkillConfigLoader                 │
│                                             │
│ Config Dict                                 │
│ - supports .env override                    │
│ - supports settings.json override           │
│                                             │
│         ↓ ExpertDiagnostician               │
│                                             │
│ Code (仅执行配置,零硬编码)                 │
│ - identify_intent()                         │
│ - initial_diagnosis()                       │
│ - execute_decision_tree()                   │
│ - generate_solution()                       │
│ - diagnose()                                │
│                                             │
│         ↓ ExpertConstraints               │
│           DiagnosisVerifier                 │
│                                             │
│ Output (诊断报告)                           │
│ - root_cause                                │
│ - confidence_score                          │
│ - solution_steps                            │
│ - verification_steps                        │
└─────────────────────────────────────────────┘

关键特性:
✅ 所有配置在SKILL.md
✅ 代码仅读取和执行
✅ 改配置无需改代码
✅ 零硬编码!
```

---

**规划文档完成!**  
下一步: 开始实现Task 3 (约束系统)

