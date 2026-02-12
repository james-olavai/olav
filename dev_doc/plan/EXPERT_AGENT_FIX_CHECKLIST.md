# Expert Agent 代码修复检查清单

**使用方法**: 按照此清单逐项完成修复，每项完成后勾选 ✅

---

## 📋 Phase 1: 诊断框架实现 (16小时)

### Step 1.1: 创建 expert_diagnostics.py 骨架 (1小时)

```bash
# 在 src/olav/agents/ 创建新文件
touch src/olav/agents/expert_diagnostics.py
```

**检查清单**:
- [ ] 文件创建
- [ ] Import必要的库
- [ ] DiagnosisIntent Enum 定义
- [ ] DiagnosisReport @dataclass 定义
- [ ] ExpertDiagnostician 类框架

**验证**:
```bash
uv run python -c "from src.olav.agents.expert_diagnostics import ExpertDiagnostician; print('✅ Import successful')"
```

---

### Step 1.2: 实现 identify_intent() 方法 (3小时)

**需要完成**:
```python
class ExpertDiagnostician:
    def identify_intent(self, query: str) -> DiagnosisIntent:
        """
        ✅ 必须:
        - 处理英文和中文
        - 返回具体的DiagnosisIntent
        - 处理歧义情况 (返回 None if unclear)
        
        ✅ 测试用例:
        """
```

**测试用例**:
```python
def test_identify_intent():
    diag = ExpertDiagnostician()
    
    # 测试1: BGP邻接诊断
    intent = diag.identify_intent("为什么BGP邻接DOWN了?")
    assert intent == DiagnosisIntent.BGP_NEIGHBOR_DOWN ✅ 
    
    # 测试2: OSPF邻接诊断
    intent = diag.identify_intent("Why is OSPF neighbor not establishing?")
    assert intent == DiagnosisIntent.OSPF_NEIGHBOR_DOWN ✅
    
    # 测试3: 设计问题
    intent = diag.identify_intent("我们的网络设计有单点故障吗?")
    assert intent == DiagnosisIntent.DESIGN_FLAW ✅
    
    # 测试4: 无法识别
    intent = diag.identify_intent("网络怎么样?")
    assert intent is None ✅
```

**检查清单**:
- [ ] 关键词字典 (BGP/OSPF/Performance/Design/Security)
- [ ] 英文支持
- [ ] 中文支持
- [ ] 歧义处理
- [ ] 所有测试通过

**验证**:
```bash
uv run pytest tests/unit/test_expert_diagnostics.py::test_identify_intent -v
```

---

### Step 1.3: 实现 initial_diagnosis() 方法 (5小时)

**核心**: 执行真实show命令收集数据,不是猜测!

```python
def initial_diagnosis(self, query: str, intent: DiagnosisIntent) -> Dict[str, Any]:
    """
    ✅ 必须:
    - 识别设备 & 邻接IP (从query中提取)
    - 执行具体CLI命令 (show ip bgp, show ospf, 等)
    - 保存实际输出 (不是模拟)
    - 进行初步分析
    - 返回证据 + 分析结果
    """
```

**每个Intent的实现** (.bgp_neighbor_down, .ospf_neighbor_down, 等):

```python
def _diagnose_bgp_neighbor_down(self, query: str) -> Dict:
    # 提取关键信息
    neighbor_ip = extract_neighbor_ip(query)
    source_device = extract_source_device(query)
    
    # 执行CLI命令 (真实执行!)
    evidence = {}
    evidence["show ip bgp summary"] = executor.run(source_device, "show ip bgp summary")
    evidence["show ip bgp neighbors"] = executor.run(source_device, f"show ip bgp neighbors {neighbor_ip}")
    evidence["show interface"] = executor.run(source_device, "show interface <extracted>")
    evidence["show run"] = executor.run(source_device, "show run | include neighbor")
    
    # 初步分析 (从证据推导)
    analysis = {
        "neighbor_state": parse_bgp_state(evidence),
        "interface_status": parse_interface_status(evidence),
        "config_issues": detect_config_mismatches(evidence),
        "l3_connectivity": check_ping(source_device, neighbor_ip)
    }
    
    return {"evidence": evidence, "analysis": analysis}
```

**检查清单**:
- [ ] _diagnose_bgp_neighbor_down() 实现
- [ ] _diagnose_ospf_neighbor_down() 实现
- [ ] _diagnose_design_flaw() 实现
- [ ] extract_neighbor_ip() helper
- [ ] extract_source_device() helper
- [ ] 解析函数 (parse_bgp_state, etc)
- [ ] 所有CLI命令实际执行 (不是模拟)
- [ ] 证据完整保存

**验证**:
```bash
# 单元测试 (使用mock的executor)
uv run pytest tests/unit/test_expert_diagnostics.py::test_initial_diagnosis_bgp -v

# 集成测试 (使用真实设备)
OLAV_TEST_MODE=integration uv run pytest tests/integration/test_expert_diagnostics.py -v
```

---

### Step 1.4: 实现 analyze_root_cause() 方法 (4小时)

**核心**: 决策树逻辑,不是LLM猜测!

```python
def analyze_root_cause(self, diagnosis: Dict, kb_cases: List) -> str:
    """
    ✅ 必须:
    - 基于诊断证据
    - 使用决策树逻辑
    - 避免"可能"/"也许"等模糊词
    - 给出具体根本原因
    """
```

**BGP邻接决策树示例**:
```
BGP邻接状态 = Idle
├─ Ping 失败?
│  ├─ YES → 三层连通性问题
│  │  ├─ 接口DOWN? → "接口置为DOWN"
│  │  └─ 路由黑洞? → "BGP到邻接的路由黑洞"
│  │
│  └─ NO → 四层问题 (TCP失败)
│     ├─ 邻接IP配置错误? → "邻接IP地址配置错误: X vs Y"
│     ├─ AS号不匹配? → "本地AS号与远端不匹配"
│     ├─ 认证失败? → "BGP认证密钥不匹配"
│     └─ TCP被拒绝? → "TCP连接被拒绝 (可能是防火墙)"

BGP邻接状态 = Active
├─ 本地主动连接邻接? → "邻接未响应,可能是远端宕机或配置问题"

BGP邻接状态 = Established ✅ (不是DOWN,无需诊断)
```

**实现模式**:
```python
def analyze_root_cause(self, diagnosis, kb_cases):
    intent = diagnosis.get('intent')
    analysis = diagnosis.get('analysis', {})
    evidence = diagnosis.get('evidence', {})
    
    if intent == DiagnosisIntent.BGP_NEIGHBOR_DOWN:
        return self._rca_bgp_neighbor_down(analysis, evidence)
    elif intent == DiagnosisIntent.OSPF_NEIGHBOR_DOWN:
        return self._rca_ospf_neighbor_down(analysis, evidence)
    # ...

def _rca_bgp_neighbor_down(self, analysis, evidence):
    state = analysis.get('neighbor_state')
    
    if state == 'Idle':
        if not analysis.get('l3_connectivity'):
            if analysis.get('interface_status') == 'Down':
                return "BGP邻接无法建立: 接口状态为DOWN"
            else:
                return "BGP邻接无法建立: 三层路由黑洞或防火墙阻断"
        else:
            config_issues = analysis.get('config_issues', [])
            if 'neighbor_ip_mismatch' in config_issues:
                return f"BGP邻接无法建立: 邻接IP配置错误"
            elif 'asn_mismatch' in config_issues:
                return f"BGP邻接无法建立: AS号配置不匹配"
            # ...
    
    # 其他状态...
    return "无法识别BGP邻接DOWN的根本原因,需要进一步诊断"
```

**检查清单**:
- [ ] _rca_bgp_neighbor_down() 实现 (决策树)
- [ ] _rca_ospf_neighbor_down() 实现 (决策树)
- [ ] _rca_design_flaw() 实现
- [ ] 所有回答避免模糊词
- [ ] 回答基于实际证据
- [ ] 决策树涵盖主要场景

**验证**:
```bash
uv run pytest tests/unit/test_expert_diagnostics.py::test_analyze_root_cause -v
```

---

### Step 1.5: 集成所有方法 (3小时)

```python
def diagnose_and_report(self, user_query: str) -> DiagnosisReport:
    """完整诊断流程"""
    
    # Step 1: 意图识别
    intent = self.identify_intent(user_query)
    if intent is None:
        # 处理无法识别的情况
        return None
    
    # Step 2: 初始诊断 (执行CLI)
    diagnosis = self.initial_diagnosis(user_query, intent)
    
    # Step 3: 知识库查询 (下一个Task)
    kb_cases = []  # TODO: 集成知识库
    
    # Step 4: RCA分析
    root_cause = self.analyze_root_cause(diagnosis, kb_cases)
    
    # Step 5: 方案生成
    solution_steps = self.generate_solution(root_cause)
    
    # Step 6: 生成报告
    report = DiagnosisReport(
        intent=intent,
        problem_description=user_query,
        diagnostic_evidence=diagnosis['evidence'],
        root_cause=root_cause,
        solution_steps=solution_steps,
        verification_steps=[s.get('verification') for s in solution_steps],
        kb_matching_cases=kb_cases,
        confidence_score=0.0  # 由验证系统赋值
    )
    
    return report
```

**检查清单**:
- [ ] diagnose_and_report() 完整实现
- [ ] 所有步骤集成
- [ ] 处理错误情况
- [ ] 返回完整DiagnosisReport

**验证**:
```bash
uv run pytest tests/unit/test_expert_diagnostics.py::test_diagnose_and_report -v
```

---

## 📋 Phase 2: 约束系统实现 (8小时)

### Step 2.1: 创建 expert_constraints.py (2小时)

```bash
touch src/olav/agents/expert_constraints.py
```

**要实现的类**:
```python
class ExpertConstraints:
    MIN_CONFIDENCE_THRESHOLD = 0.80
    MIN_EVIDENCE_PIECES = 2
    MIN_SPECIFICITY_SCORE = 0.85
    FORBIDDEN_VAGUE_TERMS = [...]
    
    @staticmethod
    def validate_diagnosis_before_output(report) -> ValidationResult:
        """检查诊断是否满足所有约束"""
        pass
```

**约束检查清单**:
- [ ] 置信度 ≥ 80%
- [ ] 证据数 ≥ 2 条
- [ ] 避免模糊词 (可能/也许/等)
- [ ] 方案都有验证步骤
- [ ] KB匹配情况正常

**检查清单**:
- [ ] ExpertConstraints 类完整
- [ ] validate_diagnosis_before_output() 实现
- [ ] 所有约束检查逻辑
- [ ] 返回清晰的错误消息

**验证**:
```bash
uv run pytest tests/unit/test_expert_constraints.py -v
```

---

### Step 2.2: 优化 LLM Prompt (3小时)

**创建or修改文件**: `src/olav/agents/expert_constraints.py` 中添加

```python
class ExpertPrompt:
    SYSTEM_PROMPT = """
你是网络诊断专家。
    
CRITICAL CONSTRAINTS:
1. ✅ 只输出通过实际show命令验证的事实
2. ❌ 不要假设你没有验证的配置
3. ❌ 禁止使用"可能"/"也许"/等模糊词
4. ✅ 必须解释你的推理基于什么证据
    """
```

**检查清单**:
- [ ] System Prompt 优化
- [ ] 输出格式规范 (JSON格式)
- [ ] 约束说明清楚
- [ ] 示例回答 (what good looks like)
- [ ] 禁止词列表

**验证**:
```bash
# 手动测试LLM输出质量
uv run python -c "
from src.olav.agents.expert_constraints import ExpertPrompt
prompt = ExpertPrompt.get_analysis_prompt(
    'Why is BGP down?',
    {'show ip bgp': 'State: Idle'},
    'BGP_NEIGHBOR_DOWN'
)
print(prompt)
"
```

---

### Step 2.3: 集成约束检查到诊断流程 (3小时)

**修改**: `src/olav/agents/expert_diagnostics.py`

```python
def diagnose_and_report(self, user_query: str) -> DiagnosisReport:
    # ... 现有代码 ...
    
    # ✅ 新增: 约束检查
    from src.olav.agents.expert_constraints import ExpertConstraints
    
    validation_result = ExpertConstraints.validate_diagnosis_before_output(report)
    
    if not validation_result.is_valid:
        logger.warning(f"诊断约束检查失败: {validation_result.issues}")
        # 决定: 返回低置信度 or 拒绝诊断
    
    return report
```

**检查清单**:
- [ ] 约束检查集成
- [ ] 返回ValidationResult
- [ ] 记录失败原因
- [ ] 根据约束决定是否输出

**验证**:
```bash
uv run pytest tests/integration/test_constraints_integration.py -v
```

---

## 📋 Phase 3: 验证系统实现 (12小时)

### Step 3.1: 创建 diagnosis_verifier.py (6小时)

```bash
touch src/olav/agents/diagnosis_verifier.py
```

**要实现的类**:
```python
class DiagnosisVerifier:
    def verify_diagnosis(self, report: DiagnosisReport, query: str) -> VerificationResult:
        """完整诊断验证"""
        pass
    
    def _verify_evidence_validity(self, report) -> Dict:
        """验证证据有效性"""
        pass
    
    def _verify_rca_logic(self, report) -> Dict:
        """验证RCA逻辑"""
        pass
    
    def _verify_solution_feasibility(self, report) -> Dict:
        """验证方案可执行性"""
        pass
```

**检查清单**:
- [ ] DiagnosisVerifier 类框架
- [ ] 5种验证类型实现
- [ ] 综合评分计算
- [ ] VerificationResult 数据结构
- [ ] 权重分配 (证据35% + RCA40% + 方案15% + KB10% + 具体性10%)

**验证**:
```bash
uv run pytest tests/unit/test_diagnosis_verifier.py::test_verify_evidence_validity -v
uv run pytest tests/unit/test_diagnosis_verifier.py::test_verify_rca_logic -v
uv run pytest tests/unit/test_diagnosis_verifier.py::test_verify_solution_feasibility -v
```

---

### Step 3.2: 集成验证到诊断流程 (4小时)

**修改**: `src/olav/agents/expert_diagnostics.py`

```python
def diagnose_and_report(self, user_query: str) -> DiagnosisReport:
    # ... 现有代码 ...
    
    # ✅ 新增: 执行验证
    from src.olav.agents.diagnosis_verifier import DiagnosisVerifier
    
    verifier = DiagnosisVerifier()
    verification_result = verifier.verify_diagnosis(report, user_query)
    
    # 赋值置信度
    report.confidence_score = verification_result.overall_score
    
    return report
```

**检查清单**:
- [ ] 验证调用集成
- [ ] 置信度自动赋值
- [ ] 验证结果记录
- [ ] 调试信息输出

**验证**:
```bash
uv run pytest tests/integration/test_diagnostic_full_flow.py -v
```

---

### Step 3.3: 落地医生诊断诊记录与学习 (2小时)

**新增功能**: 记录每个诊断的准确性

```python
class DiagnosisRecorder:
    """记录诊断结果用于持续改进"""
    
    def record_diagnosis(self, report: DiagnosisReport, verification: VerificationResult):
        """记录诊断和验证结果"""
        record = {
            "user_query": report.problem_description,
            "intent": report.intent,
            "root_cause": report.root_cause,
            "verification_score": verification.overall_score,
            "timestamp": datetime.now(),
            "kb_hits": len(report.kb_matching_cases)
        }
        
        # 存储到.olav/logs/diagnosis_results.jsonl
        save_to_jsonl(record)
    
    def get_accuracy_stats(self) -> Dict:
        """获取诊断准确率统计"""
        results = load_all_diagnosis_records()
        
        stats = {
            "total_diagnoses": len(results),
            "avg_verification_score": mean(r['verification_score'] for r in results),
            "high_confidence_ratio": sum(1 for r in results if r['verification_score'] >= 0.80) / len(results),
            "by_intent": group_by_and_stats(results, 'intent')
        }
        
        return stats
```

**检查清单**:
- [ ] DiagnosisRecorder 类实现
- [ ] JSONL格式记录
- [ ] 准确率统计计算
- [ ] 集成到诊断流程

---

## 📋 Phase 4: Orchestrator 集成 (2小时)

### Step 4.1: 修改 orchestrator_v2.py

**修改文件**: [src/olav/agents/orchestrator_v2.py#122](./src/olav/agents/orchestrator_v2.py#L122)

**变更前**:
```python
@staticmethod
def handle_expert(query: str) -> dict[str, Any]:
    result = orchestrate_query_sync(query)  # ❌ 空实现
    result["route"] = "EXPERT"
    return result
```

**变更后**:
```python
@staticmethod
def handle_expert(query: str) -> dict[str, Any]:
    """EXPERT路由: 使用新的诊断框架"""
    
    try:
        from src.olav.agents.expert_diagnostics import ExpertDiagnostician
        from src.olav.agents.diagnosis_verifier import DiagnosisVerifier
        
        diag = ExpertDiagnostician()
        report = diag.diagnose_and_report(query)
        
        # 返回诊断报告
        return {
            "status": "success",
            "route": "EXPERT",
            "diagnosis": report.__dict__,
            "confidence": report.confidence_score
        }
    
    except Exception as e:
        logger.error(f"Expert诊断失败: {e}")
        return {
            "status": "error",
            "route": "EXPERT",
            "message": str(e)
        }
```

**检查清单**:
- [ ] handle_expert() 完整修改
- [ ] Import新的诊断模块
- [ ] 返回诊断报告而非通用结果
- [ ] 异常处理

**验证**:
```bash
uv run python -c "
from src.olav.agents.orchestrator_v2 import Orchestrator
result = Orchestrator.handle_expert('为什么BGP DOWN?')
print(result)
"
```

---

## 🧪 测试验证清单

### Unit Tests (应该全部通过)

```bash
✅ 诊断框架测试 (20 tests):
   uv run pytest tests/unit/test_expert_diagnostics.py -v
   - test_identify_intent_bgp ✅
   - test_identify_intent_ospf ✅
   - test_identify_intent_design ✅
   - test_initial_diagnosis_bgp ✅
   - test_analyze_root_cause_bgp ✅
   - test_generate_solution ✅
   ... (更多测试)

✅ 约束系统测试 (10 tests):
   uv run pytest tests/unit/test_expert_constraints.py -v
   - test_validate_confidence ✅
   - test_validate_evidence ✅
   - test_catch_vague_terms ✅
   ... (更多测试)

✅ 验证系统测试 (15 tests):
   uv run pytest tests/unit/test_diagnosis_verifier.py -v
   - test_verify_evidence_validity ✅
   - test_verify_rca_logic ✅
   - test_verify_solution_feasibility ✅
   ... (更多测试)
```

### Integration Tests (使用真实设备或模拟)

```bash
✅ 完整诊断流程测试 (5 scenarios):
   OLAV_TEST_MODE=integration uv run pytest tests/integration/test_expert_full.py -v
   
   - test_scenario_bgp_neighbor_down ✅ (5分钟)
   - test_scenario_ospf_convergence_slow ✅ (5分钟)
   - test_scenario_network_asymmetry ✅ (5分钟)
   - test_scenario_design_flaw ✅ (5分钟)
   - test_scenario_cascade_failure ✅ (5分钟)
```

### Quality Checks

```bash
✅ 代码检查:
   uv run ruff check src/olav/agents/expert*.py --fix
   uv run ruff format src/olav/agents/expert*.py

✅ 类型检查:
   uv run pyright src/olav/agents/expert*.py

✅ 覆盖率检查:
   uv run pytest --cov=src.olav.agents tests/unit/ --cov-report=term-missing
   目标: ≥ 85% 覆盖率
```

---

## ✅ 项目开始检查清单

**在开始编码之前**:

- [ ] 所有开发工具已安装 (uv, pytest, ruff, pyright)
- [ ] 虚拟环境已激活
- [ ] 所有必要的依赖已安装
- [ ] 测试框架已就绪
- [ ] CI/CD 配置检查

**开始编码**:

- [ ] 创建 feature branch: `git checkout -b expert-agent-fix-phase1`
- [ ] 创建测试文件先 (TDD原则)
- [ ] 实现功能确保测试通过
- [ ] 代码审查前运行所有测试
- [ ] 创建Pull Request

---

## 📊 进度追踪模板

使用此模板记录每日进度:

```
=== 修复Day 1 ===
- [ ] 08:00-12:00: Task 1.1 & 1.2
      完成: 40% - DiagnosisIntent实现,identify_intent开发中
      
- [ ] 13:00-17:00: Task 1.2 & 1.3
      完成: 60% - identify_intent完成,initial_diagnosis开发中
      
- [ ] 17:00-20:00: Task 1.3
      完成: 80% - initial_diagnosis 80%完成,单元测试通过
      
累计进度: 60%
风险: 无
下一步: 继续 Task 1.3

=== 修复Day 2 ===
... 类似格式
```

---

## 🆘 问题排查指南

### 问题: DiagnosisReport 字段缺失

**症状**: `DiagnosisReport.__dict__` 返回不完整

**解决**:
```python
# 检查: 所有字段都赋值了吗?
report = DiagnosisReport(
    intent=intent,
    problem_description=query,  # ✅ 确保赋值
    diagnostic_evidence=evidence,
    root_cause=rca,
    solution_steps=steps,
    verification_steps=verifs,
    kb_matching_cases=cases,
    confidence_score=score  # ✅ 不要遗漏
)
```

### 问题: 验证分数总是0

**症状**: `report.confidence_score` 始终为 0.0

**解决**:
```python
# 确保 DiagnosisVerifier 被调用
verifier = DiagnosisVerifier()
verification_result = verifier.verify_diagnosis(report, query)

# ✅ 赋值置信度!
report.confidence_score = verification_result.overall_score
```

### 问题: LLM Prompt 没有被使用

**症状**: LLM 回答仍然模糊

**解决**:
```python
# 确保使用了优化的Prompt
from src.olav.agents.expert_constraints import ExpertPrompt

prompt = ExpertPrompt.get_analysis_prompt(query, evidence, intent)
# ✅ 使用这个prompt调用LLM
result = llm.invoke(prompt)
```

---

**修复指南完成!**

开始时间: ___________
预期完成: 36小时后
