# Expert Agent 快速修复指南

**时间压力**: 36小时 (Week 1)  
**目标**: 从"无法运行"→"可接受测试"

---

## 🚀 30秒快速总结

| 问题 | 当前状态 | 修复方案 | 耗时 |
|------|---------|---------|------|
| Expert完全是空 | ❌ `return orchestrate_query_sync()` | 实现诊断框架 + 5个诊断步骤 | 16h |
| 会产生幻觉 | ⚠️ LLM无约束回答 | 添加约束 + Prompt优化 | 8h |
| 无验证机制 | ❌ 诊断后无验证 | 实现自动验证系统 | 12h |

---

## 📋 修复清单 (按执行顺序)

### 任务1: 诊断框架 (16小时) 🔴 优先

**文件**: 创建 `src/olav/agents/expert_diagnostics.py`

```python
# PHASE 1: Framework Structure (4小时)
from dataclasses import dataclass
from typing import List, Dict, Any
from enum import Enum

class DiagnosisIntent(Enum):
    """诊断意图分类"""
    BGP_NEIGHBOR_Down = "bgp_neighbor_down"
    OSPF_NEIGHBOR_DOWN = "ospf_neighbor_down"
    BGP_ROUTING_BLACKHOLE = "bgp_blackhole"
    OSPF_CONVERGENCE_SLOW = "ospf_slow_convergence"
    NETWORK_ASYMMETRY = "network_asymmetry"
    DESIGN_FLAW = "design_flaw"
    PERFORMANCE_DEGRADATION = "performance_degradation"

@dataclass
class DiagnosisReport:
    """诊断报告"""
    intent: DiagnosisIntent
    problem_description: str
    diagnostic_evidence: List[Dict[str, str]]  # Command: Output pairs
    root_cause: str
    solution_steps: List[Dict[str, str]]
    verification_steps: List[str]
    kb_matching_cases: List[str]  # 匹配的知识库案例ID
    confidence_score: float  # 0.0-1.0

class ExpertDiagnostician:
    """Expert诊断核心逻辑"""
    
    # PHASE 2: Intent Recognition (3小时)
    def identify_intent(self, query: str) -> DiagnosisIntent:
        """
        识别诊断意图
        
        核心: 不仅仅是关键词匹配,还要理解上下文
        例: "为什么BGP DOWN?" → BGP_NEIGHBOR_DOWN (not just "bgp" keyword)
        """
        keywords = {
            "bgp": ["bgp", "bgp邻接", "前缀", "as路径"],
            "ospf": ["ospf", "ospf邻接", "区域", "dr"],
            "performance": ["慢", "延迟", "高", "收敛", "消耗"],
            "design": ["架构", "设计", "单点", "冗余", "扩展"],
            "security": ["黑洞", "泄露", "注入", "认证", "加密"]
        }
        
        query_lower = query.lower()
        detected_domains = []
        
        for domain, keywords_list in keywords.items():
            if any(kw in query_lower for kw in keywords_list):
                detected_domains.append(domain)
        
        # 根据域和问题类型判断具体意图
        if "bgp" in detected_domains and ("down" in query_lower or "邻接" in query_lower):
            return DiagnosisIntent.BGP_NEIGHBOR_Down
        elif "ospf" in detected_domains and ("down" in query_lower or "邻接" in query_lower):
            return DiagnosisIntent.OSPF_NEIGHBOR_DOWN
        elif "bgp" in detected_domains and ("黑洞" in query_lower or "blackhole" in query_lower):
            return DiagnosisIntent.BGP_ROUTING_BLACKHOLE
        # ... 等等
        
        return None  # 如果无法识别,返回None供稍后处理
    
    # PHASE 3: Initial Diagnostics (4小时)
    def initial_diagnosis(self, query: str, intent: DiagnosisIntent) -> Dict[str, Any]:
        """
        初始诊断: 运行基础诊断命令收集数据
        
        关键: 不是猜测,而是执行真实命令!
        """
        if intent == DiagnosisIntent.BGP_NEIGHBOR_DOWN:
            return self._diagnose_bgp_neighbor_down(query)
        elif intent == DiagnosisIntent.OSPF_NEIGHBOR_DOWN:
            return self._diagnose_ospf_neighbor_down(query)
        # ... 更多场景
    
    def _diagnose_bgp_neighbor_down(self, query: str) -> Dict[str, Any]:
        """BGP邻接DOWN诊断树"""
        
        # Step 1: 识别关键信息 (从query中提取IP/设备)
        neighbor_ip = extract_neighbor_ip(query)
        source_device = extract_source_device(query)
        
        # Step 2: 执行诊断命令 (真实CLI执行!)
        diagnostic_evidence = {}
        
        # 取证1: 邻接状态概览
        cmd = "show ip bgp summary"
        output = self.executor.run_command(source_device, cmd)
        diagnostic_evidence[cmd] = output  # 保存实际输出!
        
        # 取证2: 邻接详情
        cmd = f"show ip bgp neighbors {neighbor_ip}"
        output = self.executor.run_command(source_device, cmd)
        diagnostic_evidence[cmd] = output
        
        # 取证3: 接口状态
        neighbor_interface = extract_interface_for_neighbor(output)
        cmd = f"show interface {neighbor_interface}"
        output = self.executor.run_command(source_device, cmd)
        diagnostic_evidence[cmd] = output
        
        # 取证4: 配置检查
        cmd = "show run | include neighbor"
        output = self.executor.run_command(source_device, cmd)
        diagnostic_evidence[cmd] = output
        
        # Step 3: 基础分析 (从取证得出的事实)
        # ❌ 不要说"可能"
        # ✅ 要说"实际观察到"
        
        analysis = {
            "neighbor_state": parse_bgp_state(diagnostic_evidence),  # Idle/Active/etc
            "interface_status": parse_interface_status(diagnostic_evidence),  # Up/Down
            "config_mismatches": detect_config_issues(diagnostic_evidence),  # 配置问题列表
            "layer3_connectivity": check_l3_connectivity(source_device, neighbor_ip)  # ping结果
        }
        
        return {
            "evidence": diagnostic_evidence,
            "initial_analysis": analysis,
            "next_steps": determine_next_diagnostic_steps(analysis)
        }
    
    # PHASE 4: RCA Analysis (3小时)
    def analyze_root_cause(self, diagnosis: Dict, kb_cases: List) -> str:
        """
        根本原因分析 - 基于证据的RCA
        
        关键: 使用决策树,不是LLM猜测!
        """
        
        if diagnosis['initial_analysis']['neighbor_state'] == 'Idle':
            # 邻接无法建立TCP连接
            
            if not diagnosis['initial_analysis']['layer3_connectivity']:
                # Ping失败 → 三层连通性问题
                
                if diagnosis['initial_analysis']['interface_status'] == 'Down':
                    return "接口DOWN: " + diagnosis['evidence']['show run | include neighbor']
                else:
                    return "三层路由黑洞或防火墙阻断"
            else:
                # Ping成功但邻接Idle → 三层可达,四层问题
                
                config_issues = diagnosis['initial_analysis']['config_mismatches']
                if 'neighbor_ip_mismatch' in config_issues:
                    return f"邻接IP配置错误: 配置{config_issues['neighbor_ip_mismatch']['configured']} != 实际{config_issues['neighbor_ip_mismatch']['expected']}"
                elif 'asn_mismatch' in config_issues:
                    return f"AS号配置错误: {config_issues['asn_mismatch']}"
                elif 'auth_mismatch' in config_issues:
                    return f"认证密钥不匹配"
                else:
                    return "TCP连接被拒绝,需要进一步诊断"
        
        # ... 更多决策树分支
        
        return None
    
    # PHASE 5: Solution Generation (2小时)
    def generate_solution(self, root_cause_analysis: str) -> List[Dict[str, str]]:
        """
        方案生成 - 可执行的修复步骤
        """
        
        solutions = []
        
        if "邻接IP配置错误" in root_cause_analysis:
            solutions = [
                {
                    "step": 1,
                    "description": "进入BGP配置模式",
                    "command": "conf t; router bgp <ASN>"
                },
                {
                    "step": 2,
                    "description": "删除错误的邻接",
                    "command": "no neighbor <错误IP> remote-as <ASN>",
                    "verification": f"show run | include 'no neighbor'"
                },
                {
                    "step": 3,
                    "description": "配置正确的邻接",
                    "command": "neighbor <正确IP> remote-as <ASN>",
                    "verification": f"show run | include 'neighbor <正确IP>'"
                },
                {
                    "step": 4,
                    "description": "保存配置",
                    "command": "end; wr mem"
                },
                {
                    "step": 5,
                    "description": "验证邻接建立",
                    "command": "show ip bgp neighbors <正确IP> | include State",
                    "expected_output": "established"
                }
            ]
        
        return solutions
    
    # ✅ 集成所有步骤
    def diagnose_and_report(self, user_query: str) -> DiagnosisReport:
        """完整诊断流程"""
        
        # Step 1: 意图识别
        intent = self.identify_intent(user_query)
        
        # Step 2: 初始诊断
        diagnosis = self.initial_diagnosis(user_query, intent)
        
        # Step 3: 知识库查询 (下一个Task)
        kb_cases = self.kb_service.search_cases(intent, diagnosis)
        
        # Step 4: RCA分析
        root_cause = self.analyze_root_cause(diagnosis, kb_cases)
        
        # Step 5: 方案生成
        solution_steps = self.generate_solution(root_cause)
        
        # Step 6: 验证步骤提取
        verification_steps = extract_verification_steps(solution_steps)
        
        # Step 7: 报告生成
        report = DiagnosisReport(
            intent=intent,
            problem_description=user_query,
            diagnostic_evidence=diagnosis['evidence'],
            root_cause=root_cause,
            solution_steps=solution_steps,
            verification_steps=verification_steps,
            kb_matching_cases=kb_cases,
            confidence_score=0.0  # 由验证系统计算
        )
        
        return report
```

**检查清单**:
```
- [ ] ExpertDiagnostician 类基本框架
- [ ] identify_intent() 实现 (BGP/OSPF/等)
- [ ] initial_diagnosis() 实现 (执行真实CLI)
- [ ] analyze_root_cause() 实现 (决策树)
- [ ] generate_solution() 实现 (可执行步骤)
- [ ] diagnose_and_report() 集成
- [ ] 单元测试 (每个方法)
```

---

### 任务2: 约束系统 (8小时) 🟡 次要

**文件**: 创建 `src/olav/agents/expert_constraints.py`

```python
class ExpertConstraints:
    """确保Expert诊断高质量的约束系统"""
    
    # ✅ 必须满足的约束
    MIN_CONFIDENCE_THRESHOLD = 0.80      # 置信度≥80%
    MIN_EVIDENCE_PIECES = 2               # 至少2条证据
    MIN_SPECIFICITY_SCORE = 0.85          # 具体程度≥85%
    MIN_KB_HIT_SIMILARITY = 0.70          # KB案例相似度≥70%
    
    # ❌ 禁止的词汇 (防止幻觉)
    FORBIDDEN_VAGUE_TERMS = [
        "可能", "也许", "不确定", "取决于",
        "一般来说", "通常", "很多情况下",
        "可能导致", "也许是", "我认为",
        "似乎", "大概", "可能性包括"
    ]
    
    FORBIDDEN_PATTERNS = [
        r"可能是.*?\d+类原因",  # "可能是3类原因..."
        r"(?:可能|也许)有\d+种情况",  # "可能有5种情况"
    ]
    
    @staticmethod
    def validate_diagnosis_before_output(
        report: DiagnosisReport,
        executor_available: bool
    ) -> ValidationResult:
        """
        诊断输出前验证 - 防止幻觉的最后一道防线
        """
        issues = []
        warnings = []
        
        # Check 1: 有足够的证据吗?
        if len(report.diagnostic_evidence) < ExpertConstraints.MIN_EVIDENCE_PIECES:
            issues.append(
                f"证据不足: {len(report.diagnostic_evidence)} < {ExpertConstraints.MIN_EVIDENCE_PIECES} 条"
            )
        
        # Check 2: RCA是否包含禁止词汇?
        for term in ExpertConstraints.FORBIDDEN_VAGUE_TERMS:
            if term in report.root_cause:
                issues.append(f"RCA含有模糊词'{term}': '{report.root_cause}'")
        
        # Check 3: 方案步骤是否都有验证?
        for step in report.solution_steps:
            if "verification" not in step or not step["verification"]:
                issues.append(f"Step {step.get('step')} 缺少验证命令")
        
        # Check 4: 置信度是否合理?
        if report.confidence_score < ExpertConstraints.MIN_CONFIDENCE_THRESHOLD:
            issues.append(
                f"置信度过低: {report.confidence_score:.0%} < {ExpertConstraints.MIN_CONFIDENCE_THRESHOLD:.0%}"
            )
        
        # Check 5: KB匹配情况
        if len(report.kb_matching_cases) == 0:
            warnings.append("未找到匹配的知识库案例 - 诊断可能是新情况")
        elif len(report.kb_matching_cases) >= 3:
            # KB匹配太多=模糊 (通常意味着LLM匹配过度)
            warnings.append(f"KB匹配过多: {len(report.kb_matching_cases)} 个案例 - 诊断可能不够具体")
        
        return ValidationResult(
            is_valid=(len(issues) == 0),
            issues=issues,
            warnings=warnings,
            should_output=len(issues) == 0
        )

class ExpertPrompt:
    """专为Expert Agent优化的LLM Prompt"""
    
    SYSTEM_PROMPT = """
你是一个网络诊断专家。你的职责是精确诊断网络问题。

=== CRITICAL CONSTRAINTS ===

1. ✅ ONLY state facts verified by actual show commands
2. ❌ NEVER make assumptions about configuration you haven't verified
3. ❌ NEVER use vague terms: 可能, 也许, 不确定, 可能导致
4. ❌ NEVER suggest commands without verifying they exist
5. ✅ ALWAYS explain your reasoning based on actual data

=== OUTPUT FORMAT (MANDATORY) ===

{
  "problem_summary": "<one sentence problem statement>",
  "verified_evidence": {
    "show ip bgp summary": "<actual command output>",
    "show ip bgp neighbors <IP>": "<actual command output>"
  },
  "root_cause_analysis": {
    "primary_cause": "<SPECIFIC cause, not vague>",
    "why": "<logical reasoning from evidence>",
    "evidence_supporting": ["evidence1", "evidence2"]
  },
  "solution_steps": [
    {
      "step": "<number>",
      "action": "<what to do>",
      "command": "<exact CLI command>",
      "verification": "<command to verify it worked>"
    }
  ],
  "confidence": "<0.0-1.0>",
  "caveats": ["<assumption1>", "<unkown factor>"]
}

=== HALLUCINATION PREVENTION ===

❌ DON'T SAY:
- "可能的原因包括..."
- "也许是配置错误"
- "通常情况下..."
- "一般来说..."

✅ DO SAY:
- "从 'show ip bgp neighbors' 输出看,邻接状态是 Idle"
- "这表示TCP连接失败"
- "根本原因:邻接IP地址配置为10.0.0.99,但应该是10.0.0.2"
- "解决步骤: ..."

=== CONFIDENCE SCORING ===

- 0.9-1.0: 根据完整诊断数据确定的根本原因
- 0.7-0.9: 根据部分数据的推断,需要进一步验证
- < 0.7: 无法准确诊断,需要人工审核
"""
    
    @staticmethod
    def get_analysis_prompt(
        query: str,
        diagnostic_evidence: Dict,
        intent: str
    ) -> str:
        """为RCA生成优化的Prompt"""
        
        prompt = f"""
根据以下诊断数据,进行根本原因分析 (RCA):

=== USER QUERY ===
{query}

=== DIAGNOSTIC INTENT ===
{intent}

=== COLLECTED EVIDENCE ===
"""
        for cmd, output in diagnostic_evidence.items():
            prompt += f"""
Command: {cmd}
Output:
{output}
"""
        
        prompt += """
=== ANALYSIS TASK ===

基于上述实际采集的数据,回答:

1. 根本原因是什么? (必须基于证据,不能猜测)
2. 这个原因如何解释问题? (逻辑推导)
3. 置信度是多少? (基于证据完整性)
4. 还需要哪些信息来验证? (如果有的话)

=== CONSTRAINTS ===
- ✅ 必须直接引用上述证据
- ❌ 禁止使用"可能", "也许", "通常"
- ✅ 必须给出具体的根本原因 (不是列举可能性)
- ❌ 如果无法确定,说"无法确定,原因是X"而不是"可能是..."

Response Format:
{
    "root_cause": "具体原因",
    "supporting_evidence": ["证据1相关部分", "证据2相关部分"],
    "reasoning": "为什么这是根本原因",
    "confidence": 0.85,
    "still_uncertain_about": ["未验证的假设1", "未验证的假设2"]
}
"""
        return prompt
```

**检查清单**:
```
- [ ] ExpertConstraints 约束类
- [ ] validate_diagnosis_before_output() 方法
- [ ] FORBIDDEN_VAGUE_TERMS 检查
- [ ] ExpertPrompt 优化的System Prompt
- [ ] 集成到 orchestrator_v2.py
- [ ] 测试约束检查逻辑
```

---

### 任务3: 验证系统 (12小时) 🔴 优先

**文件**: 创建 `src/olav/agents/diagnosis_verifier.py`

```python
class DiagnosisVerifier:
    """诊断验证系统 - 自动评估诊断质量"""
    
    def verify_diagnosis(
        self,
        report: DiagnosisReport,
        user_query: str
    ) -> VerificationResult:
        """完整诊断验证"""
        
        checks = {
            "evidence_validity": self._verify_evidence_validity(report),
            "rca_logic": self._verify_rca_logic(report),
            "solution_feasibility": self._verify_solution_feasibility(report),
            "kb_correlation": self._verify_kb_correlation(report),
            "specificity": self._verify_specificity(report)
        }
        
        # 计算综合评分
        overall_score = sum(
            check['score'] * check['weight']
            for check in checks.values()
        ) / sum(check['weight'] for check in checks.values())
        
        return VerificationResult(
            checks=checks,
            overall_score=overall_score,
            is_reliable=(overall_score >= 0.80),
            confidence_level=classify_confidence(overall_score)
        )
    
    def _verify_evidence_validity(self, report: DiagnosisReport) -> Dict:
        """验证: 诊断证据的有效性"""
        
        checks_passed = 0
        total_checks = 0
        
        for cmd, output in report.diagnostic_evidence.items():
            total_checks += 1
            
            # Check 1: 命令是否有效?
            if self._is_valid_command(cmd):
                checks_passed += 1
            
            # Check 2: 输出是否有内容?
            if output and len(output.strip()) > 0:
                checks_passed += 1
            else:
                total_checks += 1  # 两个独立检查
        
        score = checks_passed / total_checks if total_checks > 0 else 0.0
        
        return {
            "score": score,
            "weight": 0.35,  # 证据权重较高
            "details": f"{checks_passed}/{total_checks} 检查通过"
        }
    
    def _verify_rca_logic(self, report: DiagnosisReport) -> Dict:
        """验证: RCA逻辑的合理性"""
        
        issues = []
        
        # Check 1: RCA是否具体?
        if any(term in report.root_cause for term in VAGUE_TERMS):
            issues.append("RCA包含模糊表述")
        
        # Check 2: RCA是否与证据一致?
        for cmd, output in report.diagnostic_evidence.items():
            if not self._is_rca_supported_by_evidence(report.root_cause, cmd, output):
                issues.append(f"RCA未被'{cmd}'输出支持")
        
        # Check 3: RCA是否可验证?
        try:
            verification_cmds = extract_verification_commands(report.root_cause)
            if len(verification_cmds) == 0:
                issues.append("RCA无法通过命令验证")
        except:
            issues.append("RCA逻辑系统错误")
        
        score = 1.0 - (len(issues) * 0.2)  # 每个问题-20分
        
        return {
            "score": max(0, score),
            "weight": 0.40,  # RCA权重最高
            "details": f"{len(issues)} 个逻辑问题"
        }
    
    def _verify_solution_feasibility(self, report: DiagnosisReport) -> Dict:
        """验证: 解决方案的可执行性"""
        
        issues = []
        
        for step in report.solution_steps:
            # Check 1: 命令是否存在?
            cmd = step.get('command', '')
            if not self._command_exists(cmd):
                issues.append(f"Step {step.get('step')} 中的命令不存在: {cmd}")
            
            # Check 2: 是否有验证步骤?
            if not step.get('verification'):
                issues.append(f"Step {step.get('step')} 缺少验证命令")
            
            # Check 3: 前置条件是否满足?
            if step.get('prerequisites'):
                if not all(self._prerequisite_met(p) for p in step['prerequisites']):
                    issues.append(f"Step {step.get('step')} 前置条件未满足")
        
        score = 1.0 - (len(issues) / len(report.solution_steps) * 0.2)
        
        return {
            "score": max(0, score),
            "weight": 0.15,
            "details": f"{len(issues)} 个可执行性问题"
        }
    
    def _verify_kb_correlation(self, report: DiagnosisReport) -> Dict:
        """验证: 知识库关联"""
        
        # 没有KB匹配 = 信号 (可能是新情况)
        if len(report.kb_matching_cases) == 0:
            score = 0.60  # 降低分数,但不是失败
            reasoning = "未找到相关知识库案例,诊断可能是新情况"
        
        # 多个高相似度匹配 = 强信号
        elif len(report.kb_matching_cases) >= 2:
            score = 0.95
            reasoning = f"发现{len(report.kb_matching_cases)}个高相关知识库案例"
        
        # 1个匹配 = 弱信号
        else:
            score = 0.75
            reasoning = "发现1个相关知识库案例"
        
        return {
            "score": score,
            "weight": 0.10,
            "details": reasoning
        }
    
    def _verify_specificity(self, report: DiagnosisReport) -> Dict:
        """验证: 回答的具体程度 (防止幻觉)"""
        
        # 让LLM评估自己的具体程度
        specificity_prompt = f"""
评估以下诊断的具体程度 (0.0-1.0):

根本原因: {report.root_cause}

评分标准:
- 1.0: 非常具体, 指向单一明确原因 ("邻接IP配置为10.0.0.99,应为10.0.0.2")
- 0.75: 较具体, 指向某个系统或模块 ("BGP认证配置不匹配")
- 0.5: 中等具体, 可能涉及多个原因 ("配置或连通性问题")
- 0.25: 较模糊, 很多可能 ("可能是网络或配置问题")
- 0.0: 非常模糊, 无重点 ("可能是多种原因导致")

返回: {"specificity_score": 0.85, "reasoning": "..."}
"""
        
        eval_result = self.llm.invoke(specificity_prompt)
        specificity_score = eval_result.get('specificity_score', 0.5)
        
        return {
            "score": specificity_score,
            "weight": 0.10,
            "details": eval_result.get('reasoning', '')
        }
```

**检查清单**:
```
- [ ] DiagnosisVerifier 基本类
- [ ] _verify_evidence_validity() 实现
- [ ] _verify_rca_logic() 实现
- [ ] _verify_solution_feasibility() 实现
- [ ] _verify_kb_correlation() 实现
- [ ] _verify_specificity() 实现
- [ ] 综合评分计算
- [ ] 集成到诊断流程
```

---

### 任务4: 集成到 Orchestrator (2小时) 🟡 次要

**修改**: [src/olav/agents/orchestrator_v2.py#122](./src/olav/agents/orchestrator_v2.py#L122)

```python
@staticmethod
def handle_expert(query: str) -> dict[str, Any]:
    """EXPERT路由: 复杂诊断和分析"""
    
    logger.info(f"🧠 Expert route: {query[:60]}...")
    
    try:
        # ✅ 新增: 使用Expert诊断框架!
        from olav.agents.expert_diagnostics import ExpertDiagnostician
        from olav.agents.diagnosis_verifier import DiagnosisVerifier
        from olav.agents.expert_constraints import ExpertConstraints
        
        diagnostician = ExpertDiagnostician()
        verifier = DiagnosisVerifier()
        
        # Step 1: 执行诊断
        report = diagnostician.diagnose_and_report(query)
        
        # Step 2: 验证诊断
        verification_result = verifier.verify_diagnosis(report, query)
        
        # Step 3: 约束检查
        constraint_result = ExpertConstraints.validate_diagnosis_before_output(report)
        
        # Step 4: 决策 - 是否输出?
        if not constraint_result.should_output:
            logger.warning(f"⚠️ Diagnosis failed constraint checks: {constraint_result.issues}")
            return {
                "status": "low_confidence",
                "route": "EXPERT",
                "reason": "诊断置信度不足,建议人工审核",
                "issues": constraint_result.issues,
                "diagnosis": report.__dict__  # 仍然返回诊断供审核
            }
        
        # Step 5: 检查验证分数
        if verification_result.overall_score < 0.70:
            logger.warning(f"⚠️ Diagnosis verification score low: {verification_result.overall_score:.0%}")
        
        # Step 6: 生成响应
        return {
            "status": "success",
            "route": "EXPERT",
            "diagnosis": DiagnosisReport_to_dict(report),
            "verification": {
                "overall_score": verification_result.overall_score,
                "confidence_level": verification_result.confidence_level,
                "checks": {k: v['score'] for k, v in verification_result.checks.items()}
            },
            "final_answer": format_diagnosis_report(report)  # 用户可读输出
        }
        
    except Exception as e:
        logger.error(f"❌ Expert route failed: {e}", exc_info=True)
        return {
            "status": "error",
            "route": "EXPERT",
            "message": f"Expert诊断失败: {str(e)}"
        }
```

---

## 📅 时间表 (36小时)

```timeline
Day 1 (12小时):
├─ 08:00-12:00: Task 1 - 诊断框架基础 (4h)
├─ 13:00-17:00: Task 1 - 诊断树实现 (4h)
└─ 17:00-20:00: Task 1 - 集成与单元测试 (3h)

Day 2 (12小时):
├─ 08:00-12:00: Task 2 - 约束系统 (4h)
├─ 13:00-17:00: Task 2 - Prompt优化 (4h)
└─ 17:00-20:00: Task 2 - 集成测试 (2h)

Day 3 (12小时):
├─ 08:00-14:00: Task 3 - 验证系统实现 (6h)
├─ 14:00-18:00: Task 3 - 验证集成 (4h)
└─ 18:00-20:00: Task 4 - Orchestrator集成 (2h)

Day 4: 压力测试与修复 (缓冲)
```

---

## ✅ 定义完成

诊断完成标准:

```
✅ Unit Tests Pass (70/70)
   └─ Diagnostician: 20 tests
   └─ Verifier: 15 tests
   └─ Constraints: 10 tests
   └─ Integration: 25 tests

✅ Manual Verification (3/3 scenarios)
   └─ Scenario 1: BGP Down (Execute & Verify)
   └─ Scenario 2: OSPF Convergence (Execute & Verify)
   └─ Scenario 3: Design Flaw (Execute & Verify)

✅ Quality Metrics
   └─ Hallucination Rate < 5%
   └─ Specificity Score ≥ 85%
   └─ Verification Pass Rate ≥ 90%
   └─ RCA Accuracy ≥ 80%

✅ Code Quality
   └─ Zero critical issues
   └─ 100% constraint validation coverage
   └─ All edge cases handled
```

---

## 🚨 风险缓解

**如果修复未完成**:

| 时间 | 状态 | 行动 |
|------|------|------|
| 12h后 | Task 1未完成 | 🔴 立即升级,分配更多人力 |
| 24h后 | Task 2未完成 | 🟡 危险,可能无法赶上Week 2测试 |  
| 30h后 | Task 3 ≤50% | 🟡 延期Expert测试,先做Query/CLI/Analysis |

**备选方案**: 
- 如果无法完成所有功能,**至少**完成Task 1 + Task 2 (24小时)
- Task 3可以延到Week 2

---

这就是完整修复计划! 建议立即开始Task 1。
