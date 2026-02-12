# Expert Agent 代码缺陷与幻觉风险分析

**分析日期**: 2026年2月11日  
**严重程度**: 🔴 高  
**优先级**: P0 (阻碍性)

---

## 📋 执行摘要

Expert Agent 当前实现存在 **3个关键缺陷** 和 **高幻觉风险**：

| 缺陷 | 类型 | 影响 | 风险 |
|------|------|------|------|
| #1 | 空实现 | Expert完全委托给Orchestrator,无真实诊断 | 🔴 高 |
| #2 | 约束缺失 | LLM无确定性约束,回答过于宽泛 | 🔴 高 |  
| #3 | 验证机制缺失 | 无诊断结果验证,易产生幻觉 | 🔴 高 |

**整体评估**: ❌ **当前不符合测试要求**,需要立即补充完整实现

---

## 🔴 缺陷详情

### 缺陷 #1: Expert Agent 完全空实现

**位置**: 
- [src/olav/agents/orchestrator_v2.py#122-144](./src/olav/agents/orchestrator_v2.py#L122)
- [src/olav/agents/guard.py#1049-1072](./src/olav/agents/guard.py#L1049)

**问题代码**:
```python
@staticmethod
def handle_expert(query: str) -> dict[str, Any]:
    """EXPERT route: Complex analysis queries."""
    logger.info(f"🧠 Expert route: {query[:60]}...")
    
    try:
        # ❌ 问题: 直接委托给Orchestrator,没有任何Expert诊断逻辑!
        result = orchestrate_query_sync(query)
        result["route"] = "EXPERT"
        return result
    except Exception as e:
        logger.error(f"❌ Expert route error: {e}")
        return {"status": "error", "message": f"Expert analysis failed: {str(e)}", ...}
```

**症状**:
```python
# 以下任何查询都会被委托给Orchestrator
query1 = "诊断为什么BGP邻接不稳定?"
query2 = "根本原因分析: OSPF邻接DOWN"
query3 = "设计缺陷: 我们的网络有单点故障吗?"

# ❌ 结果: 所有查询都进入通用Orchestrator,没有Expert特化处理!
result = handle_expert(query1)  # → orchestrate_query_sync(query1)
result = handle_expert(query2)  # → orchestrate_query_sync(query2)
result = handle_expert(query3)  # → orchestrate_query_sync(query3)
```

**影响**:
- ❌ 无法执行诊断树决策逻辑
- ❌ 无法调用知识库匹配
- ❌ 无法进行多步诊断
- ❌ Expert indicators在Guard中定义但无人使用

**根本原因**:
```
Expert Agent设计 → 测试计划 ✅
Expert Agent实现 → 完全缺失 ❌

测试计划描述了应该做什么,但代码中根本没有这样做
```

**修复方案** (P0 - 立即修复):
```python
@staticmethod
def handle_expert(query: str) -> dict[str, Any]:
    """EXPERT route: Complex diagnosis & analysis."""
    logger.info(f"🧠 Expert route: {query[:60]}...")
    
    try:
        # ✅ 新增: Expert诊断流程
        from olav.agents.expert_diagnostics import ExpertDiagnostician
        
        diagnostician = ExpertDiagnostician()
        
        # Step 1: 意图识别
        intent = diagnostician.identify_intent(query)  # BGP/OSPF/Design/etc
        
        # Step 2: 初始诊断
        initial_diagnosis = diagnostician.initial_diagnosis(query, intent)
        
        # Step 3: 知识库查询
        kb_cases = diagnostician.search_knowledge_base(intent, initial_diagnosis)
        
        # Step 4: RCA分析
        root_cause = diagnostician.analyze_root_cause(initial_diagnosis, kb_cases)
        
        # Step 5: 方案生成
        solution = diagnostician.generate_solution(root_cause)
        
        # Step 6: 报告生成
        report = diagnostician.generate_report(initial_diagnosis, root_cause, solution)
        
        return {
            "status": "success",
            "route": "EXPERT",
            "intent": intent,
            "diagnosis": initial_diagnosis,
            "root_cause": root_cause,
            "solution": solution,
            "report": report,
            "kb_hits": len(kb_cases)
        }
    except Exception as e:
        logger.error(f"❌ Expert analysis failed: {e}")
        return {"status": "error", "route": "EXPERT", "message": str(e)}
```

---

### 缺陷 #2: LLM 约束缺失导致高幻觉风险

**问题**: Expert Agent使用LLM进行诊断，但缺少约束条件确保回答的**精准性和具体性**

**示例 - 高幻觉风险**:

```
User Query: "为什么BGP邻接不稳定?"

❌ 当前LLM回答 (Too General):
───────────────────────────────────
根本原因可能包括:
1. 网络配置问题
2. 设备资源不足
3. 网络连接问题
4. 操作系统问题
5. ...很多其他可能

这个答案:
- 太宽泛,没有具体指向
- 用户实际需要: 具体的诊断(邻接地址错误/AS号不匹配/认证失败)
- 导致用户继续困惑

✅ 所需回答 (Specific & Concrete):
───────────────────────────────────
根本原因: BGP邻接配置错误

具体表现:
1. 邻接状态: Idle (无法建立TCP连接)
2. 本地配置检查:
   R1# show run | include neighbor
   → neighbor 10.0.0.99 remote-as 65001  ❌ 错误!
3. 预期配置:
   → neighbor 10.0.0.2 remote-as 65001
4. 问题: 邻接IP地址不匹配 (10.0.0.99 vs 10.0.0.2)

解决步骤:
1. conf t
2. router bgp 65000
3. no neighbor 10.0.0.99
4. neighbor 10.0.0.2 remote-as 65001
5. exit
6. wr mem

验证:
R1# show ip bgp neighbors 10.0.0.2
→ BGP state = Established ✅

这个答案:
- 具体指向根本原因
- 提供可执行的诊断步骤
- 可验证的解决方案
```

**幻觉风险具体表现**:

| 场景 | 幻觉类型 | 风险 | 示例 |
|------|---------|------|------|
| BGP诊断 | 过度声称 | 中 | "邻接问题100%是认证失败" (实际可能是配置错误) |
| OSPF诊断 | 不确定性 | 中 | "可能有Area mismatch,也可能是计时器问题" (缺乏确定性) |
| 设计分析 | 虚构风险 | 高 | "假设了不存在的拓扑结构" (未经验证的假设) |
| 方案建议 | 不可行性 | 高 | "建议修改不存在的参数" (基于虚构的理解) |

**幻觉根本原因**:
```python
# ❌ 当前LLM Prompt (缺少约束)
system_prompt = """
You are an Expert Network Agent.
Analyze network problems and provide solutions.
"""

# 问题: 没有约束!
# - 没有规定输出格式
# - 没有约束回答的具体程度
# - 没有要求证据支持
# - 没有禁止虚构信息

✅ 改进的LLM Prompt (有约束):
system_prompt = """
You are an Expert Network Diagnostician.

CRITICAL CONSTRAINTS FOR ACCURACY:
1. ✅ ONLY output facts verified by actual commands (show ip bgp, show ospf, etc)
2. ❌ NEVER make assumptions about configuration you haven't verified
3. ❌ NEVER suggest commands without confirming they exist on the platform
4. ✅ ALWAYS provide diagnostic evidence & reasoning
5. ✅ ALWAYS include verification steps to confirm diagnosis

OUTPUT FORMAT (MANDATORY):
{
  "problem_classification": "<具体问题类型>",
  "confidence": <0.0-1.0>,  # 诊断置信度
  "verified_evidence": [
    {
      "command": "show ip bgp neighbors",
      "output": "State: Idle",  # 实际命令输出
      "interpretation": "无法建立邻接连接"
    },
    ...
  ],
  "root_cause": {
    "primary": "<主要原因>",
    "evidence": ["证据1", "证据2"],
    "why_this_cause": "<逻辑推导>"
  },
  "solution_steps": [
    {
      "step": 1,
      "action": "修改邻接地址",
      "command": "neighbor 10.0.0.2 remote-as 65001",
      "verification": "show ip bgp neighbors 10.0.0.2 | include State"
    }
  ],
  "hallucination_risk": "<low|medium|high>",
  "caveats": ["前提条件1", "未验证的假设2"]
}

HALLUCINATION PREVENTION:
- ❌ NEVER say "可能是..." or "也许..." without evidence
- ✅ If uncertain → say "需要进一步诊断" with next steps
- ❌ NEVER assume platform supports a command
- ✅ If command not verified → list as "to be confirmed"
"""
```

**修复方案** (P0 - 立即修复):

创建约束系统:
```python
class ExpertConstraints:
    """确保Expert Agent诊断的约束系统"""
    
    # 1. 诊断确定性约束
    MIN_CONFIDENCE_THRESHOLD = 0.80  # 诊断置信度必须>80%
    
    # 2. 证据要求约束
    REQUIRE_EVIDENCE = True  # 所有诊断必须有证据支持
    MIN_EVIDENCE_COUNT = 2   # 至少2条独立证据
    
    # 3. 回答具体性约束
    MIN_SPECIFICITY = 0.85   # 回答具体程度评分
    DISALLOW_VAGUE_TERMS = [
        "可能", "也许", "不确定", "取决于",
        "可能导致", "也许是", "一般来说"
    ]
    
    # 4. 知识库匹配约束
    MIN_KB_HIT_SIMILARITY = 0.70  # KB案例相似度>70%
    
    # 5. 解决方案验证约束
    REQUIRE_VERIFICATION_STEPS = True
    
    @staticmethod
    def validate_diagnosis(diagnosis: DiagnosisReport) -> ValidationResult:
        """验证诊断是否满足所有约束"""
        
        issues = []
        
        # Check 1: 置信度
        if diagnosis.confidence < ExpertConstraints.MIN_CONFIDENCE_THRESHOLD:
            issues.append(
                f"诊断置信度过低: {diagnosis.confidence:.0%} < {ExpertConstraints.MIN_CONFIDENCE_THRESHOLD:.0%}"
            )
        
        # Check 2: 证据数量
        if len(diagnosis.evidence) < ExpertConstraints.MIN_EVIDENCE_COUNT:
            issues.append(
                f"证据不足: {len(diagnosis.evidence)} < {ExpertConstraints.MIN_EVIDENCE_COUNT}"
            )
        
        # Check 3: 回答具体性
        for vague_term in ExpertConstraints.DISALLOW_VAGUE_TERMS:
            if vague_term in diagnosis.root_cause:
                issues.append(f"回答过于宽泛,包含模糊词:{vague_term}")
        
        # Check 4: 验证步骤
        if diagnosis.solution_steps and len(diagnosis.solution_steps) > 0:
            for step in diagnosis.solution_steps:
                if not step.get("verification"):
                    issues.append(f"Step {step.get('step')} 缺少验证步骤")
        
        return ValidationResult(
            is_valid=len(issues) == 0,
            issues=issues
        )
```

---

### 缺陷 #3: 诊断验证机制完全缺失

**问题**: 没有验证Expert诊断是否正确的机制

**影响**:
```
Expert诊断 → 出现幻觉 → 没有反馈机制发现问题 → 问题积累
```

**示例**:
```
Scenario 1: BGP邻接诊断
User Query: "为什么BGP邻接DOWN了?"

Expert回答 (虚构):
"原因: BGP进程中断了,需要重启"

❌ 问题: 
- 没有实际查看show ip bgp进程状态
- 没有验证这是否真的是根因
- 用户重启后问题依然存在 → 回答错误!

✅ 需要的验证流程:
1. 诊断后立即获取验证数据
2. 对比预期 vs 实际
3. 评分诊断准确性
4. 记录失败案例用于改进
```

**当前缺失的验证代码**:

```python
# ❌ 现有代码: 没有验证
def handle_expert(query: str):
    result = orchestrate_query_sync(query)  # 诊断
    return result  # 直接返回,无验证!

# ✅ 需要的代码:
def handle_expert_with_verification(query: str):
    # Step 1: 诊断
    diagnosis = expert_diagnostician.diagnose(query)
    
    # Step 2: 验证 (新增!)
    verification_result = expert_diagnostician.verify_diagnosis(
        diagnosis=diagnosis,
        query=query
    )
    
    # Step 3: 评估准确性
    accuracy_score = calculate_accuracy(verification_result)
    
    # Step 4: 记录
    log_diagnosis_result(
        query=query,
        diagnosis=diagnosis,
        verification=verification_result,
        accuracy=accuracy_score
    )
    
    # Step 5: 三层防护
    if accuracy_score < 0.7:
        return {
            "status": "low_confidence",
            "diagnosis": diagnosis,
            "accuracy_score": accuracy_score,
            "warning": "诊断置信度低,建议人工审核"
        }
    
    return {
        "status": "success",
        "diagnosis": diagnosis,
        "accuracy_score": accuracy_score
    }
```

**修复方案** (P0 - 立即修复):

```python
class DiagnosisVerifier:
    """诊断验证系统"""
    
    def verify_diagnosis(self, diagnosis: DiagnosisReport, query: str) -> VerificationResult:
        """验证诊断是否正确"""
        
        checks = []
        
        # Check 1: 证据验证
        for evidence in diagnosis.evidence:
            evidence_check = self._verify_evidence(evidence)
            checks.append(evidence_check)
        
        # Check 2: 根本原因验证
        rca_check = self._verify_root_cause(diagnosis.root_cause)
        checks.append(rca_check)
        
        # Check 3: 解决方案可执行性
        solution_check = self._verify_solution(diagnosis.solution_steps)
        checks.append(solution_check)
        
        # Check 4: 知识库验证
        kb_check = self._verify_kb_match(diagnosis, diagnosis.kb_hit_cases)
        checks.append(kb_check)
        
        # 综合评分
        overall_score = sum(c.score for c in checks) / len(checks)
        
        return VerificationResult(
            checks=checks,
            overall_score=overall_score,
            is_reliable=(overall_score >= 0.80)
        )
    
    def _verify_evidence(self, evidence: Evidence) -> VerificationCheck:
        """验证单个证据"""
        
        # 执行命令,对比输出
        actual_output = execute_command(
            device=evidence.device,
            command=evidence.command
        )
        
        match_score = calculate_similarity(
            evidence.actual_output,
            actual_output
        )
        
        return VerificationCheck(
            type="evidence",
            name=evidence.command,
            score=match_score,
            passed=(match_score > 0.85),
            details=f"Similarity: {match_score:.0%}"
        )
    
    def _verify_root_cause(self, root_cause: str) -> VerificationCheck:
        """验证根本原因分析"""
        
        # 1. 检查KB是否有相同或相似的根因
        kb_matches = search_knowledge_base(root_cause)
        
        # 2. 检查根因分析逻辑是否完整
        logic_check = validate_reasoning_logic(root_cause)
        
        # 3. 检查根因是否可验证
        verification_possible = can_verify_root_cause(root_cause)
        
        score = (
            (len(kb_matches) > 0 and 0.3 or 0.0) +  # KB匹配
            (logic_check and 0.4 or 0.0) +           # 逻辑完整
            (verification_possible and 0.3 or 0.0)   # 可验证
        )
        
        return VerificationCheck(
            type="root_cause",
            score=score,
            passed=(score > 0.70)
        )
    
    def _verify_solution(self, solution_steps: List[SolutionStep]) -> VerificationCheck:
        """验证解决方案"""
        
        issues = []
        
        for step in solution_steps:
            # 检查命令是否存在
            if not command_exists(step.command):
                issues.append(f"命令不存在: {step.command}")
            
            # 检查验证步骤
            if not step.verification:
                issues.append(f"Step {step.step} 缺少验证")
            
            # 检查前置依赖
            if not all_prerequisites_met(step):
                issues.append(f"Step {step.step} 前置条件未满足")
        
        score = 1.0 - (len(issues) / max(len(solution_steps), 1) * 0.1)
        
        return VerificationCheck(
            type="solution",
            score=max(0, score),
            passed=(len(issues) == 0),
            issues=issues
        )
```

---

## 📊 缺陷影响评估

### 按严重程度排序

| 缺陷 | 当前状态 | 影响 | 修复时间 | 优先级 |
|------|---------|------|---------|--------|
| #1 Expert空实现 | ❌ 无 | 无法执行诊断 | 16小时 | P0 |
| #2 幻觉风险 | ⚠️ 高 | 输出不精准 | 8小时 | P0 |
| #3 验证机制缺失 | ❌ 无 | 无法发现错误 | 12小时 | P0 |

### 测试计划可行性评估

```
当前状态:         不可行 ❌
所需修复:        3个P0缺陷
修复后可行:      ✅ 可以进行第1-3周测试

Timeline:
Week 1 (现在)    → 修复P0缺陷 (36小时开发)
Week 2           → Phase 1测试 (BGP/OSPF诊断)
Week 3-5         → 完整测试计划
```

---

## ✅ 修复检查清单

### Phase 1: 实现诊断框架 (16小时)

```
- [ ] 创建 ExpertDiagnostician 类
      └─ 5个诊断阶段实现
      └─ BGP/OSPF诊断树编码
      └─ 知识库查询集成
      └─ RCA逻辑实现
      
- [ ] 创建 DiagnosisVerifier 类
      └─ 证据验证
      └─ 根因验证
      └─ 方案验证
      └─ 准确性评分
      
- [ ] 实现handle_expert 完整逻辑
      └─ 意图识别
      └─ 诊断执行
      └─ 验证与评分
      └─ 报告生成
```

### Phase 2: 添加约束系统 (8小时)

```
- [ ] 创建 ExpertConstraints 类
      └─ 置信度约束 (≥80%)
      └─ 证据要求 (≥2条)
      └─ 具体性约束 (≥85%)
      └─ KB匹配约束 (≥70%)
      
- [ ] 优化LLM Prompt
      └─ 添加约束说明
      └─ 规定输出格式
      └─ 禁止幻觉项
      └─ 要求验证步骤
      
- [ ] 实现Validation方法
      └─ 约束检查
      └─ 风险评估
      └─ 自动拒绝机制
```

### Phase 3: 验证系统集成 (12小时)

```
- [ ] 集成诊断验证
      └─ 实时验证运行
      └─ 准确性评分
      └─ 失败案例记录
      
- [ ] 建立反馈循环
      └─ 诊断结果日志
      └─ 准确性统计
      └─ 自动改进触发
      
- [ ] 测试验证系统
      └─ 使用故障注入工具
      └─ 验证诊断正确性
      └─ 测量准确率
```

---

## 🎯 关键建议

### 立即行动 (今天)

1. **创建Expert诊断框架**
   ```python
   # 新文件: src/olav/agents/expert_diagnostics.py
   class ExpertDiagnostician:
       def diagnose(self, query: str) -> DiagnosisReport: pass
       def identify_intent(self, query: str) -> str: pass
       def initial_diagnosis(self, query: str, intent: str) -> Dict: pass
       def search_knowledge_base(self, intent: str, diagnosis: Dict) -> List: pass
       def analyze_root_cause(self, diagnosis: Dict, kb_cases: List) -> str: pass
       def generate_solution(self, root_cause: str) -> List[SolutionStep]: pass
       def generate_report(self, diagn, rca, solution) -> str: pass
   ```

2. **添加诊断约束**
   ```python
   # 新文件: src/olav/agents/expert_constraints.py
   class ExpertConstraints:
       MIN_CONFIDENCE_THRESHOLD = 0.80
       MIN_EVIDENCE_COUNT = 2
       DISALLOW_VAGUE_TERMS = [...]
       @staticmethod
       def validate_diagnosis(diagnosis) -> ValidationResult: pass
   ```

3. **实现验证系统**
   ```python
   # 新文件: src/olav/agents/diagnosis_verifier.py
   class DiagnosisVerifier:
       def verify_diagnosis(self, diagnosis, query) -> VerificationResult: pass
       def _verify_evidence(self, evidence) -> VerificationCheck: pass
       def _verify_root_cause(self, root_cause) -> VerificationCheck: pass
       def _verify_solution(self, solution) -> VerificationCheck: pass
   ```

### 风险缓解

**如果无法在Week 1完成修复**:
- ⛔ 暂停Expert测试计划
- ✅ 先完成Query/CLI/Analysis Agent测试 (已就绪)
- ⏰ 延期Expert测试到Week 3

**预计风险**: 
- 🔴 高 - 当前实现不满足测试要求
- 🟡 中 - 修复后可能仍有边界情况问题
- 🟢 低 - 修复+验证后应该稳定

---

## 📈 成功标准

修复完成后应满足:

```
✅ Expert诊断准确率 ≥ 85%
   - 根据故障注入测试评估
   - 30个测试场景通过

✅ 幻觉率 < 5%
   - LLM回答具体程度 ≥ 80%
   - 避免使用"可能/也许"等模糊词

✅ 验证覆盖率 100%
   - 所有诊断都经过验证
   - 准确性评分自动计算

✅ 约束满足率 100%
   - 所有诊断满足置信度约束
   - 所有方案都有验证步骤
```

---

## 📞 后续行动

1. **确认修复资源**: 需要1名全栈开发工程师, 36小时
2. **调整测试时间表**: 延期Expert测试1周
3. **建立验收标准**: 签字同意修复方案

---

**缺陷分析完成**  
**优先级**: 🔴 P0 (阻碍性)  
**建议**: 立即开始修复,不建议开始测试前推进
