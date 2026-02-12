"""
Expert Diagnostic Framework - Skill-Driven Architecture

所有诊断配置从 .olav/skills/network-expert/SKILL_DIAGNOSTIC_WORKFLOW.md 读取
零硬编码,完全由SKILL驱动
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


class SkillConfigLoader:
    """从SKILL.md加载所有诊断配置"""
    
    SKILL_PATH = Path(".olav/skills/network-expert/SKILL_DIAGNOSTIC_WORKFLOW.md")
    
    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        """
        加载SKILL配置 (包含frontmatter YAML)
        
        优先级:
        1. .env (EXPERT_* 变量)
        2. .olav/settings.json (expert section)
        3. SKILL.md frontmatter (this file)
        4. config/settings.py (defaults)
        """
        
        # 1. 读取SKILL frontmatter
        skill_config = cls._extract_frontmatter_yaml()
        
        # 2. 读取.olav/settings.json覆盖
        settings_overrides = cls._load_settings_json_overrides()
        
        # 3. 读取.env覆盖
        env_overrides = cls._load_env_overrides()
        
        # 4. 合并配置 (优先级: env > settings.json > SKILL)
        final_config = cls._merge_configs(skill_config, settings_overrides, env_overrides)
        
        logger.info(f"✅ Loaded Expert diagnostic config from SKILL")
        return final_config
    
    @classmethod
    def _extract_frontmatter_yaml(cls) -> Dict[str, Any]:
        """提取SKILL.md中的frontmatter YAML"""
        import yaml
        
        with open(cls.SKILL_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 提取---...---之间的YAML
        start = content.find('```yaml\n---\n') + len('```yaml\n')
        end = content.find('\n---\n```', start)
        
        if start == -1 or end == -1:
            logger.warning("⚠️  无法从SKILL提取frontmatter")
            return {}
        
        yaml_content = content[start:end]
        config = yaml.safe_load(yaml_content)
        
        return config or {}
    
    @classmethod
    def _load_settings_json_overrides(cls) -> Dict[str, Any]:
        """从.olav/settings.json加载覆盖"""
        settings_path = Path(".olav/settings.json")
        
        if not settings_path.exists():
            return {}
        
        with open(settings_path, 'r') as f:
            settings = json.load(f)
        
        return settings.get("expert", {})
    
    @classmethod
    def _load_env_overrides(cls) -> Dict[str, Any]:
        """从.env加载EXPERT_*环境变量"""
        import os
        
        overrides = {}
        
        # EXPERT_CONFIDENCE_THRESHOLD
        if "EXPERT_CONFIDENCE_THRESHOLD" in os.environ:
            overrides["confidence_threshold"] = float(
                os.environ["EXPERT_CONFIDENCE_THRESHOLD"]
            )
        
        # EXPERT_FORBIDDEN_TERMS
        if "EXPERT_FORBIDDEN_TERMS" in os.environ:
            overrides["forbidden_terms"] = os.environ["EXPERT_FORBIDDEN_TERMS"].split(",")
        
        # ... 更多环境变量覆盖
        
        return overrides
    
    @classmethod
    def _merge_configs(cls, skill_config, settings_overrides, env_overrides) -> Dict:
        """合并配置 (优先级: env > settings > skill)"""
        
        merged = {**skill_config}
        
        # 应用settings.json覆盖
        for key, value in settings_overrides.items():
            if key in merged and isinstance(merged[key], dict):
                merged[key].update(value)
            else:
                merged[key] = value
        
        # 应用.env覆盖
        for key, value in env_overrides.items():
            if key in merged and isinstance(merged[key], dict):
                merged[key].update(value)
            else:
                merged[key] = value
        
        return merged


# ============================================================================
# 诊断配置数据结构
# ============================================================================

@dataclass
class DiagnosticIntent:
    """诊断意图定义 (从SKILL读取)"""
    name: str
    display_name: str
    keywords: List[str]
    required_commands: List[str]
    decision_tree: str
    confidence_baseline: float


@dataclass
class Constraint:
    """单个约束 (从SKILL读取)"""
    name: str
    value: Any
    action_on_fail: str
    description: str


@dataclass
class VerificationRule:
    """验证规则 (从SKILL读取)"""
    rule_id: str
    check_description: str
    pass_score: float
    fail_score: float


@dataclass
class SolutionTemplate:
    """解决方案模板 (从SKILL读取)"""
    name: str
    description: str
    steps: List[Dict[str, str]]
    expected_result: str
    verification_command: Optional[str] = None


@dataclass
class DiagnosisReport:
    """诊断报告"""
    intent: str
    problem_description: str
    diagnostic_evidence: Dict[str, str]  # command -> output
    root_cause: str
    solution_steps: List[Dict[str, str]]
    verification_steps: List[str]
    kb_matching_cases: List[str]
    confidence_score: float
    generated_at: str
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# 诊断框架核心
# ============================================================================

class ExpertDiagnostician:
    """
    Expert诊断框架 - Skill驱动
    
    所有配置从SKILL.md读取,零硬编码
    """
    
    def __init__(self):
        """初始化: 从SKILL加载所有配置"""
        
        # 加载SKILL配置
        self.config = SkillConfigLoader.load_config()
        
        # 初始化约束、验证规则等
        self._init_constraints()
        self._init_verification_rules()
        self._init_solution_templates()
        self._init_diagnostic_trees()
        
        logger.info("✅ ExpertDiagnostician initialized with SKILL config")
    
    def _init_constraints(self):
        """从SKILL.constraints初始化约束"""
        self.constraints = self.config.get("constraints", {})
        
        # 示例: 获取置信度约束
        self.min_confidence = self.constraints.get("confidence", {}).get("min_threshold", 0.80)
        self.forbidden_terms = (
            self.constraints.get("specificity", {}).get("forbidden_terms", [])
        )
        
        logger.debug(f"✅ Constraints loaded: min_confidence={self.min_confidence}")
    
    def _init_verification_rules(self):
        """从SKILL.verification初始化验证规则"""
        self.verification_rules = self.config.get("verification", {})
        logger.debug(f"✅ Verification rules loaded: {len(self.verification_rules)} rule sets")
    
    def _init_solution_templates(self):
        """从SKILL.solution_templates初始化方案模板"""
        self.solution_templates = self.config.get("solution_templates", {})
        logger.debug(f"✅ Solution templates loaded: {len(self.solution_templates)} templates")
    
    def _init_diagnostic_trees(self):
        """从SKILL.diagnostic_trees初始化诊断树"""
        self.diagnostic_trees = self.config.get("diagnostic_trees", {})
        logger.debug(f"✅ Diagnostic trees loaded: {list(self.diagnostic_trees.keys())}")
    
    # ========================================================================
    # Phase 1: 意图识别
    # ========================================================================
    
    def identify_intent(self, query: str) -> Optional[str]:
        """
        识别诊断意图 (从SKILL.diagnostic_intents读取关键词)
        
        Args:
            query: 用户查询
            
        Returns:
            intent name or None if cannot identify
        """
        
        query_lower = query.lower()
        
        # 从SKILL读取所有已定义的诊断意图
        diagnostic_intents = self.config.get("diagnostic_intents", {})
        
        for intent_name, intent_config in diagnostic_intents.items():
            keywords = intent_config.get("keywords", [])
            
            # 检查是否所有关键词都在query中
            if all(kw.lower() in query_lower for kw in keywords[:2]):  # 至少2个关键词
                logger.info(f"✅ Intent identified: {intent_name}")
                return intent_name
        
        logger.warning(f"⚠️  Cannot identify intent for: {query[:60]}")
        return None
    
    # ========================================================================
    # Phase 2: 初始诊断 (执行CLI命令)
    # ========================================================================
    
    def initial_diagnosis(self, query: str, intent: str) -> Dict[str, Any]:
        """
        执行初始诊断 (从SKILL.diagnostic_intents[intent].required_commands读取要执行的命令)
        
        Returns:
            {
                "intent": intent,
                "evidence": {command -> output},
                "analysis": {...}
            }
        """
        
        # 从SKILL读取此Intent的必需命令
        intent_config = self.config["diagnostic_intents"].get(intent, {})
        required_commands = intent_config.get("required_commands", [])
        
        logger.info(f"Executing {len(required_commands)} diagnostic commands for {intent}")
        
        # 收集证据 (模拟执行,实际应该连接真实设备)
        evidence = {}
        
        for cmd in required_commands:
            # 实际实现: executor.run_command()
            output = self._execute_command_mock(cmd)
            evidence[cmd] = output
            logger.debug(f"  ✓ Executed: {cmd}")
        
        # 初步分析 (这里非常简化,实际应该使用决策树)
        analysis = {
            "command_count": len(evidence),
            "all_commands_successful": all(v for v in evidence.values())
        }
        
        return {
            "intent": intent,
            "evidence": evidence,
            "analysis": analysis
        }
    
    def _execute_command_mock(self, command: str) -> str:
        """
        模拟执行命令 (实际应该使用nornir或netmiko)
        
        在真实实现中,这会:
        1. 连接到设备
        2. 执行CLI命令
        3. 获取实际输出
        """
        
        # 模拟数据
        mock_outputs = {
            "show ip bgp summary": """
            BGP router identifier 1.1.1.1, local AS number 65001
            
            Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
            10.0.0.2        4 65002   12345   12340   123456    0    0 12:34:56 12345
            """,
            "show ip bgp neighbors": """
            BGP neighbor is 10.0.0.2,  remote AS 65002, internal link
              Member of peer-group iBGP for session parameters
              BGP version 4
              Remote router ID 2.2.2.2
              BGP state = Established, up for 12w3d
            """,
            "show interface": """
            Ethernet0/0 is up, line protocol is up
              Hardware is Ethernet, address is 0001.0001.0001 (bia 0001.0001.0001)
              Internet address is 10.0.0.1/30
              MTU 1500 bytes, BW 1000000 Kbit
            """
        }
        
        return mock_outputs.get(command, f"[Mock output for: {command}]")
    
    # ========================================================================
    # Phase 3: 决策树分析
    # ========================================================================
    
    def execute_decision_tree(self, intent: str, evidence: Dict) -> Dict[str, str]:
        """
        按决策树进行根本原因分析 (从SKILL.diagnostic_trees[intent]读取树逻辑)
        
        Returns:
            {
                "root_cause": "具体根本原因",
                "decision_path": ["node1", "node2", ...],
                "evidence_used": ["cmd1", "cmd2"]
            }
        """
        
        # 从SKILL读取诊断树
        tree_name = (
            self.config["diagnostic_intents"][intent].get("decision_tree", "")
        )
        
        if tree_name not in self.diagnostic_trees:
            logger.error(f"❌ Tree not found: {tree_name}")
            return {"root_cause": "无法确定根本原因"}
        
        tree = self.diagnostic_trees[tree_name]
        
        # 按树的逻辑进行决策 (简化示例)
        logger.info(f"Executing decision tree: {tree_name}")
        
        decision_path = []
        current_node = tree.get("root_check", "unknown")
        
        # 示例: BGP邻接诊断树
        if "bgp" in current_node.lower():
            # Check 1: 邻接状态
            for cmd, output in evidence.items():
                if "show ip bgp" in cmd and "Established" in output:
                    return {
                        "root_cause": "BGP邻接已正常建立",
                        "decision_path": decision_path,
                        "evidence_used": list(evidence.keys()),
                        "confidence": 0.95
                    }
                elif "Idle" in output:
                    return {
                        "root_cause": "BGP邻接无法建立连接,需要进一步诊断",
                        "decision_path": decision_path,
                        "evidence_used": list(evidence.keys()),
                        "confidence": 0.70
                    }
        
        return {
            "root_cause": "根本原因待定",
            "decision_path": decision_path,
            "evidence_used": list(evidence.keys()),
            "confidence": 0.50
        }
    
    # ========================================================================
    # Phase 4: 生成解决方案
    # ========================================================================
    
    def generate_solution(self, root_cause: str) -> List[Dict[str, str]]:
        """
        从SKILL.solution_templates生成修复方案
        
        根据根本原因,选择对应的解决方案模板
        """
        
        solution_templates = self.solution_templates
        
        # 简化: 根据root_cause关键词选择模板
        selected_template = None
        
        for template_name, template in solution_templates.items():
            if any(kw in root_cause for kw in ["接口", "interface"]):
                selected_template = solution_templates.get("interface_up")
                break
            elif any(kw in root_cause for kw in ["邻接IP", "neighbor", "IP配置"]):
                selected_template = solution_templates.get("fix_neighbor_ip")
                break
        
        if not selected_template:
            # 无法找到匹配的模板
            logger.warning(f"⚠️  No solution template for: {root_cause}")
            return []
        
        # 返回从SKILL读取的方案步骤
        return selected_template.get("steps", [])
    
    # ========================================================================
    # Phase 5: 完整诊断流程
    # ========================================================================
    
    def diagnose(self, query: str) -> DiagnosisReport:
        """
        完整诊断流程 (所有配置从SKILL读取)
        
        Step 1: 意图识别
        Step 2: 执行诊断命令
        Step 3: 按决策树分析
        Step 4: 生成解决方案
        Step 5: 返回报告
        """
        
        from datetime import datetime
        
        logger.info(f"🧠 Starting diagnosis for: {query[:60]}")
        logger.info(f"⚙️  Using SKILL config: {self.config.get('name', 'unknown')}")
        
        # Step 1: 意图识别
        intent = self.identify_intent(query)
        if not intent:
            return DiagnosisReport(
                intent="unknown",
                problem_description=query,
                diagnostic_evidence={},
                root_cause="无法识别诊断意图",
                solution_steps=[],
                verification_steps=[],
                kb_matching_cases=[],
                confidence_score=0.0,
                generated_at=datetime.now().isoformat()
            )
        
        # Step 2: 初始诊断 (执行CLI)
        diagnosis = self.initial_diagnosis(query, intent)
        
        # Step 3: 决策树分析
        rca_result = self.execute_decision_tree(intent, diagnosis["evidence"])
        root_cause = rca_result.get("root_cause", "")
        confidence = rca_result.get("confidence", 0.5)
        
        # Step 4: 生成解决方案
        solution_steps = self.generate_solution(root_cause)
        
        # Step 5: 生成验证步骤
        verification_steps = [
            step.get("verification", "")
            for step in solution_steps
            if step.get("verification")
        ]
        
        # 生成报告
        report = DiagnosisReport(
            intent=intent,
            problem_description=query,
            diagnostic_evidence=diagnosis["evidence"],
            root_cause=root_cause,
            solution_steps=solution_steps,
            verification_steps=verification_steps,
            kb_matching_cases=[],  # TODO: 知识库集成
            confidence_score=confidence,
            generated_at=datetime.now().isoformat()
        )
        
        logger.info(f"✅ Diagnosis complete: confidence={confidence:.0%}, intent={intent}")
        
        return report


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    import logging
    
    logging.basicConfig(level=logging.DEBUG)
    
    # 创建诊断师 (从SKILL加载配置)
    diagnostician = ExpertDiagnostician()
    
    # 执行诊断
    query = "为什么BGP邻接DOWN了?"
    report = diagnostician.diagnose(query)
    
    # 输出报告
    print("\n" + "="*60)
    print(f"Diagnosis Report: {report.intent}")
    print("="*60)
    print(f"Root Cause: {report.root_cause}")
    print(f"Confidence: {report.confidence_score:.0%}")
    print(f"Solution Steps: {len(report.solution_steps)}")
    print(f"Generated at: {report.generated_at}")
