# Network Expert Agent - Diagnostic Workflow Configuration

**Version**: 1.0.0  
**Status**: Skill-Centric Architecture (Zero Hardcoding)  
**Design Pattern**: Configuration-Driven Diagnostics  

---

## 📋 Frontmatter Configuration

```yaml
---
name: network-expert-diagnostician
version: 1.0.0
description: CCIE-level diagnostic expert with skill-driven workflow
author: Network AI Team
type: agent
category: network-analysis
intent: expert_diagnosis

# ✅ 工作流完全来自此SKILL配置，零硬编码
workflow_source: skill  # 不是代码,是配置!
cache_enabled: false    # Expert诊断总是实时
confidence_threshold: 0.80
hallucination_prevention: enabled

# 诊断意图配置 (从此读取,不从代码读取)
diagnostic_intents:
  bgp_neighbor_down:
    display_name: "BGP邻接诊断"
    keywords: ["bgp", "neighbor", "down", "邻接"]
    required_commands:
      - "show ip bgp summary"
      - "show ip bgp neighbors"
      - "show interface"
      - "show ip bgp neighbors {neighbor_ip}"
    decision_tree: "diagnostic_trees.bgp_neighbor_down"
    confidence_baseline: 0.85
    
  ospf_neighbor_down:
    display_name: "OSPF邻接诊断"
    keywords: ["ospf", "neighbor", "down", "邻接"]
    required_commands:
      - "show ip ospf neighbor"
      - "show ip ospf interface"
      - "show interface"
      - "show ip route ospf"
    decision_tree: "diagnostic_trees.ospf_neighbor_down"
    confidence_baseline: 0.80

# 约束配置 (从此读取,不从代码写死)
constraints:
  confidence:
    min_threshold: 0.80
    action_on_fail: reject_output
    
  evidence:
    min_pieces: 2
    required_types: ["cli_output", "config_check"]
    action_on_fail: request_more_data
    
  specificity:
    min_score: 0.85
    forbidden_terms: ["可能", "也许", "不确定", "可能导致", "也许是"]
    action_on_fail: regenerate_answer
    
  solution:
    require_verification_steps: true
    require_expected_output: true
    max_manual_steps: 10
    
# 验证配置 (从此读取,不是代码逻辑)
validation:
  evidence_validity:
    weight: 0.35
    checks:
      - command_exists
      - output_not_empty
      - output_parseable
      
  rca_logic:
    weight: 0.40
    checks:
      - free_of_vague_terms
      - supported_by_evidence
      - single_clear_cause
      
  solution_feasibility:
    weight: 0.15
    checks:
      - commands_exist
      - has_verification
      - prerequisites_met
      
  kb_correlation:
    weight: 0.10
    checks:
      - case_similarity_score  # ≥ 0.70
      
  answer_specificity:
    weight: 0.10
    checks:
      - no_generic_statements
      - specific_values_referenced
      - actionable_guidance

# 知识库配置
knowledge_base:
  cases_dir: ".olav/knowledge/cases"
  similarity_threshold: 0.70
  auto_save_diagnosis: true
  learning_enabled: true
  
# 工具链配置 (从此读取执行顺序)
tool_chain:
  1_data_collection:
    tools: ["cli_executor", "config_parser"]
    timeout: 30
    
  2_analysis:
    tools: ["decision_tree_engine", "pattern_matcher"]
    timeout: 10
    
  3_rca:
    tools: ["logic_validator", "evidence_mapper"]
    timeout: 10
    
  4_solution:
    tools: ["command_suggester", "verification_builder"]
    timeout: 5
    
  5_verification:
    tools: ["diagnosis_verifier", "accuracy_scorer"]
    timeout: 5
---
```

---

## 🏗️ Diagnostic Tree Configuration (Skill-Defined)

### BGP邻接DOWN诊断树

```yaml
diagnostic_trees:
  bgp_neighbor_down:
    description: "BGP邻接无法建立的诊断树"
    root_check: "neighbor_state"
    
    decision_nodes:
      # Node 1: 邻接状态检查
      neighbor_state:
        command: "show ip bgp neighbors {neighbor_ip}"
        extract_field: "BGP state"
        branches:
          Idle:
            next_node: "layer3_check"
            interpretation: "无法建立TCP连接"
          Active:
            result:
              root_cause: "邻接未响应,本地主动连接中"
              severity: "high"
              solution_template: "verify_remote_config"
          Established:
            result:
              root_cause: "邻接已正常建立"
              severity: "none"
              action: "no_action_needed"
      
      # Node 2: 三层连通性检查
      layer3_check:
        command: "ping {neighbor_ip}"
        extract_field: "success"
        branches:
          false:  # Ping失败
            next_node: "interface_check"
            interpretation: "三层连通性问题"
          true:   # Ping成功
            next_node: "config_mismatch_check"
            interpretation: "三层可达,问题在BGP层"
      
      # Node 3: 接口状态检查
      interface_check:
        command: "show interface {connecting_interface}"
        extract_field: "line_protocol"
        branches:
          down:
            result:
              root_cause: "连接接口状态为DOWN"
              evidence: ["interface_status"]
              solution_template: "interface_up"
          up:
            result:
              root_cause: "三层路由黑洞或防火墙阻断"
              evidence: ["ping_failed", "interface_up"]
              solution_template: "routing_blackhole"
      
      # Node 4: 配置检查
      config_mismatch_check:
        command: "show run | include neighbor"
        extract_fields:
          - "neighbor_ip"
          - "remote_as"
          - "password"
        branches:
          neighbor_ip_mismatch:
            result:
              root_cause: "邻接IP配置错误"
              evidence: ["show_run", "config_comparison"]
              solution_template: "fix_neighbor_ip"
          asn_mismatch:
            result:
              root_cause: "AS号配置不匹配"
              evidence: ["show_run", "asn_comparison"]
              solution_template: "fix_asn"
          auth_failure:
            result:
              root_cause: "BGP认证密钥不匹配"
              evidence: ["show_run", "auth_config"]
              solution_template: "fix_authentication"
          no_issues_found:
            next_node: "bgp_process_check"
            interpretation: "配置看起来正确,检查BGP进程"
      
      # Node 5: BGP进程检查
      bgp_process_check:
        command: "show ip bgp summary"
        extract_field: "local_as_status"
        branches:
          down:
            result:
              root_cause: "本地BGP进程未运行"
              solution_template: "restart_bgp"
          up:
            result:
              root_cause: "无法确定根本原因,需要人工审核"
              confidence: 0.45
              recommendation: "enable_debug_bgp"

# 解决方案模板 (从SKILL读取，不硬编码)
solution_templates:
  interface_up:
    description: "启用接口"
    steps:
      - command: "conf t"
        verification: null
      - command: "interface {interface_name}"
        verification: null
      - command: "no shutdown"
        verification: "show interface {interface_name} | include protocol"
      - command: "end"
        verification: null
      - command: "wr mem"
        verification: "verify config saved"
    expected_result: "Interface line protocol becomes UP"
    
  fix_neighbor_ip:
    description: "修复邻接IP地址配置"
    steps:
      - command: "conf t"
      - command: "router bgp {local_asn}"
      - command: "no neighbor {incorrect_ip} remote-as {remote_asn}"
        verification: "show run | include 'no neighbor'"
      - command: "neighbor {correct_ip} remote-as {remote_asn}"
        verification: "show run | include 'neighbor {correct_ip}'"
      - command: "end"
      - command: "wr mem"
    expected_result: "BGP neighbor state becomes Established"
    verification_command: "show ip bgp neighbors {correct_ip} | include State"

  routing_blackhole:
    description: "诊断和修复路由黑洞"
    steps:
      - command: "show ip route {neighbor_ip} detail"
        verification: "identify_next_hop"
      - command: "traceroute {neighbor_ip}"
        verification: "identify_failure_point"
    expected_result: "Route to neighbor identified or added"
    
  restart_bgp:
    description: "重启BGP进程"
    warning: "This will interrupt all BGP sessions"
    steps:
      - command: "conf t"
      - command: "router bgp {asn}"
      - command: "shutdown"
      - command: "no shutdown"
      - command: "end"
    expected_result: "BGP neighbors re-establish"
    verification_command: "show ip bgp summary"

# 约束配置 (从SKILL读取，检查器执行)
constraints_rules:
  forbidden_terms:
    terms: ["可能", "也许", "不确定", "取决于", "一般来说", "通常", "可能导致"]
    action: "reject_if_contains_any"
    message: "回答包含模糊词,不符合Expert要求"
  
  evidence_requirement:
    min_count: 2
    required_sources: ["cli_output"]
    action: "request_more_data"
    
  confidence_requirement:
    min_score: 0.80
    action: "downgrade_to_medium_confidence"
    
  solution_requirement:
    needs_verification: true
    action: "add_verification_steps"
```

---

## 🔍 Verification Rules (Skill-Defined)

```yaml
verification_rules:
  evidence_validity:
    rules:
      - rule_id: "cmd_exists"
        check: "command_is_valid_cisco_command(cmd)"
        pass_score: 1.0
        fail_score: 0.0
        
      - rule_id: "output_not_empty"
        check: "command_output.length > 50"
        pass_score: 1.0
        fail_score: 0.5
        
      - rule_id: "output_parseable"
        check: "can_parse_output_to_dict(output)"
        pass_score: 1.0
        fail_score: 0.3
  
  rca_logic:
    rules:
      - rule_id: "free_of_vague"
        check: "not_contains_vague_terms(rca)"
        pass_score: 1.0
        fail_score: 0.0
        
      - rule_id: "evidence_support"
        check: "rca_referenced_in_evidence()"
        pass_score: 1.0
        fail_score: 0.2
        
      - rule_id: "single_cause"
        check: "rca_points_to_one_root_cause()"
        pass_score: 1.0
        fail_score: 0.5
  
  solution_feasibility:
    rules:
      - rule_id: "commands_exist"
        check: "each_command_exists_on_platform(commands)"
        pass_score: 1.0
        fail_score: 0.0
        
      - rule_id: "has_verification"
        check: "each_step_has_verification()"
        pass_score: 1.0
        fail_score: 0.3
        
      - rule_id: "prerequisites_met"
        check: "all_prerequisites_satisfied()"
        pass_score: 1.0
        fail_score: 0.4

# 特异性检查 (防止幻觉)
specificity_checks:
  requires:
    - "具体的设备/邻接IP"
    - "实际的配置值" 
    - "特定的命令输出"
    - "可执行的修复步骤"
  
  forbidden_patterns:
    - "可能(是|会|导致)"
    - "也许(是|会)"
    - "一般来说"
    - "取决于"
    - "通常情况"
```

---

## 🔧 Tool Chain Configuration

```yaml
tool_chain_config:
  # Phase 1: 数据收集 (从SKILL配置读取要执行的命令)
  data_collection:
    executor: "cli_executor"
    timeout_per_command: 10
    timeout_total: 30
    concurrency: 1  # 顺序执行
    retry_failed: true
    retry_attempts: 2
    
  # Phase 2: 初始分析 (从决策树执行)
  initial_analysis:
    engine: "decision_tree_engine"
    tree_source: "skill.diagnostic_trees"  # ← 从SKILL读取!
    timeout: 10
    caching: false
    
  # Phase 3: RCA分析 (从决策树输出推导)
  rca_analysis:
    logic: "evidence_based_rca"  # 不是LLM猜测
    timeout: 10
    
  # Phase 4: 方案生成 (从SKILL的solution_templates读取)
  solution_generation:
    templates_source: "skill.solution_templates"  # ← 从SKILL读取!
    timeout: 5
    
  # Phase 5: 验证系统 (从SKILL的verification_rules读取)
  verification:
    rules_source: "skill.verification_rules"  # ← 从SKILL读取!
    timeout: 5
    min_pass_score: 0.80
```

---

## 📝 LLM Prompts (Enhanced with Skill Config)

```yaml
prompts:
  system: |
    你是Network Expert Agent - CCIE级别的网络诊断专家。
    
    你的所有诊断工作流来自SKILL配置,不是硬编码逻辑。
    
    **诊断过程** (从SKILL.diagnostic_trees读取):
    1. 意图识别 → 选择对应的决策树
    2. 执行诊断命令 (从SKILL.diagnostic_intents[intent].required_commands读取)
    3. 按决策树进行推导
    4. 输出根本原因
    5. 从SKILL.solution_templates生成修复方案
    6. 按SKILL.verification_rules验证
    
    **约束** (从SKILL.constraints读取):
    - 置信度 ≥ {confidence_threshold}
    - 证据数 ≥ {min_evidence_pieces}  
    - 禁止词: {forbidden_terms}
    - 必须具体,不能模糊
    
    **验证规则** (从SKILL.verification_rules读取):
    - 证据有效性: {evidence_validity.rules}
    - RCA逻辑: {rca_logic.rules}
    - 方案可执行: {solution_feasibility.rules}
  
  analysis: |
    基于收集的数据进行诊断:
    
    设备数据:
    {device_data}
    
    执行的诊断命令:
    {diagnostic_commands}
    
    决策树路径 (from SKILL):
    {decision_tree_path}
    
    请按以下步骤回答:
    1. 确认邻接状态
    2. 按决策树逐层分析
    3. 得出单一根本原因 (非列举可能性!)
    4. 提供具体修复步骤 (从SKILL.solution_templates)
    5. 包含验证命令
    
    约束检查 (from SKILL.constraints):
    ✅ 避免使用词: {forbidden_terms}
    ✅ 回答必须具体,引用实际值
    ✅ 每个步骤都要验证
    ✅ 置信度要≥ {confidence_threshold}
  
  validation: |
    按SKILL.verification_rules验证此诊断:
    
    {verification_rules_text}
    
    为诊断评分:
    - 证据有效性 (权重 0.35): __/1.0
    - RCA逻辑 (权重 0.40): __/1.0  
    - 方案可执行 (权重 0.15): __/1.0
    - KB相关性 (权重 0.10): __/1.0
    
    综合评分 = (证据×0.35 + RCA×0.40 + 方案×0.15 + KB×0.10)
    
    若综合评分 < {confidence_threshold}:
    - 输出状态: LOW_CONFIDENCE
    - 不输出给用户,建议人工审核
```

---

## 🎯 Integration Points (Code Reads from Skill)

代码**绝不**硬编码任何配置,全部从SKILL.md读取:

```python
# ❌ 错误 (硬编码)
MIN_CONFIDENCE = 0.80
FORBIDDEN_TERMS = ["可能", "也许"]
REQUIRED_COMMANDS = ["show ip bgp summary", ...]

# ✅ 正确 (从SKILL读取)
config = load_skill_config("network-expert-diagnostician")
MIN_CONFIDENCE = config.constraints.confidence.min_threshold
FORBIDDEN_TERMS = config.constraints.specificity.forbidden_terms
REQUIRED_COMMANDS = config.diagnostic_intents[intent].required_commands

decision_trees = config.diagnostic_trees
solution_templates = config.solution_templates
verification_rules = config.verification

# 工具执行顺序从SKILL读取
for phase_name, phase_config in config.tool_chain.items():
    execute_phase(phase_name, phase_config)
```

---

## 🚀 Configuration Override Chain (OLAV Standard)

优先级 (高 → 低):

1. **`.env` 文件** (运行时环境变量)
   ```bash
   EXPERT_CONFIDENCE_THRESHOLD=0.90
   EXPERT_FORBIDDEN_TERMS="可能,也许,不确定"
   ```

2. **`.olav/settings.json`** (用户全局设置)
   ```json
   {
     "expert": {
       "confidence_threshold": 0.85,
       "max_decision_depth": 8
     }
   }
   ```

3. **`SKILL.md` frontmatter** (技能特定配置) ← 本文件
   ```yaml
   confidence_threshold: 0.80
   diagnostic_intents: [...]
   ```

4. **`config/settings.py`** (默认配置)
   ```python
   EXPERT_DEFAULT_CONFIDENCE = 0.75
   ```

---

## 📊 Configuration Loading Code Pattern

```python
class ExpertSkillConfig:
    @staticmethod
    def load_from_skill() -> ExpertConfig:
        """Load all configuration from SKILL.md only"""
        
        # 1. 读取SKILL.md frontmatter YAML
        skill_path = Path(".olav/skills/network-expert/SKILL_DIAGNOSTIC_WORKFLOW.md")
        skill_yaml = extract_frontmatter(skill_path)
        
        # 2. 用.env和settings.json覆盖
        env_overrides = load_env_overrides("EXPERT_")
        settings_overrides = load_settings_json("expert")
        
        # 3. 合并配置 (优先级: env > settings.json > SKILL)
        config = ExpertConfig(
            confidence_threshold=env_overrides.get(
                "confidence_threshold",
                settings_overrides.get(
                    "confidence_threshold",
                    skill_yaml.get("confidence_threshold")
                )
            ),
            diagnostic_intents=skill_yaml.get("diagnostic_intents"),
            constraints=skill_yaml.get("constraints"),
            solution_templates=skill_yaml.get("solution_templates"),
            verification_rules=skill_yaml.get("verification_rules"),
            tool_chain_config=skill_yaml.get("tool_chain_config"),
        )
        
        return config

# 使用
config = ExpertSkillConfig.load_from_skill()
MIN_CONFIDENCE = config.confidence_threshold  # 从SKILL读取!
DIAGNOSTIC_INTENTS = config.diagnostic_intents  # 从SKILL读取!
SOLUTION_TEMPLATES = config.solution_templates  # 从SKILL读取!
```

---

## ✅ Benefits of Skill-Centric Approach

| 方面 | 硬编码 | Skill配置 |
|------|--------|----------|
| 修改诊断树 | 改代码,重新部署 | 改SKILL.md,立即生效 ✅ |
| 修改约束 | 改代码,重新部署 | 改SKILL.md,立即生效 ✅ |
| 修改工具链 | 改代码,重新部署 | 改SKILL.md,立即生效 ✅ |
| 用户定制 | 代码分支,维护复杂 | settings.json,清晰 ✅ |
| 可读性 | 代码嵌套,难理解 | YAML配置,一目了然 ✅ |
| 可维护性 | 代码改动风险 | 配置改动,零风险 ✅ |
| 扩展性 | 修改代码+逻辑 | 增加配置段 ✅ |

---

**配置驱动设计完成!**  
所有诊断逻辑来自SKILL.md,代码仅执行配置。零硬编码,完全灵活。

