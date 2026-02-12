# 07. Expert Agent - 完整参考指南

**版本**: v1.0.0  
**日期**: 2026-02-11  
**状态**: ✅ 生产就绪

---

## 📚 目录

1. [架构概述](#架构概述)
2. [核心模块](#核心模块)
3. [报告生成系统](#报告生成系统)
4. [验证管道](#验证管道)
5. [决策路由](#决策路由)
6. [使用示例](#使用示例)
7. [API参考](#api参考)
8. [最佳实践](#最佳实践)
9. [故障排除](#故障排除)

---

## 架构概述

### 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│ Expert Agent 诊断输出                                        │
│ (root_cause, solution, recovery_cmds, verification_steps)   │
└────────────────────┬────────────────────────────────────────┘
                     │
              ┌──────▼────────┐
              │ Orchestrator  │
              │  (验证管道)   │
              └──────┬────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
    约束验证    准确性验证    决策网关
    (Task4)    (Task5)      (可选)
        │            │            │
        └────────────┼────────────┘
                     │
        ┌────────────▼────────────┐
        │  OrchestratorReport     │
        │  (结构化诊断报告)        │
        │  - constraint_score     │
        │  - accuracy_score       │
        │  - decision             │
        │  - routing              │
        └──────────┬─────────────┘
                   │
         ┌─────────┴────────────┐
         ▼                      ▼
    返回用户              队列审核
   (ACCEPT)           (FLAG/REJECT)
```

### 关键特性

| 特性 | 说明 |
|------|------|
| **约束验证** | 检测幻觉、确保诊断完整性 (Task 4) |
| **准确性验证** | 与Ground Truth对比准确率 (Task 5) |
| **决策网关** | 自动或人工审核诊断质量 |
| **报告生成** | 多格式输出 (Markdown/JSON) |
| **路由决策** | 自动路由到用户或审核队列 |
| **可审计** | 完整的诊断追踪和日志 |

---

## 核心模块

### 1. OrchestratorReport (Pydantic模型)

**位置**: `src/olav/orchestrator/expert_orchestrator.py`

**核心字段**:

```python
class OrchestratorReport(BaseModel):
    # 标识
    scenario_id: str              # 诊断ID (e.g., "bgp_timeout_issue")
    timestamp: datetime           # 生成时间
    batch_id: Optional[str]       # 批量处理ID
    
    # 决策信息
    overall_decision: DecisionType              # ACCEPT/FLAG/REJECT/ESCALATE
    routing_decision: RoutingDecision           # 路由目标
    reason: str                                 # 决策理由
    
    # 分数
    constraint_score: float      # 约束验证分数 [0, 1]
    accuracy_score: Optional[float]             # 准确性分数 [0, 1]
    hybrid_score: Optional[float]               # 混合分数
    confidence_score: float      # Expert置信度 [0, 1]
    
    # 诊断信息
    expert_diagnosis: ExpertDiagnosis           # 完整诊断
    
    # 质量问题
    critical_failures: List[str]                # 关键失败
    warnings: List[str]                         # 警告
    improvement_suggestions: List[str]          # 改进建议
    
    # 性能
    execution_time_ms: float     # 执行时间
```

### 2. ExpertOrchestrator (协调器)

**核心方法**:

```python
class ExpertOrchestrator:
    async def process(
        self,
        diagnosis: ExpertDiagnosis,
        ground_truth: Optional[dict] = None,
    ) -> OrchestratorReport:
        """
        处理Expert诊断并生成验证报告
        
        参数:
            diagnosis: Expert Agent的诊断输出
            ground_truth: 可选的Ground Truth数据
        
        返回:
            OrchestratorReport (包含所有验证结果)
        """
        # 1. 约束验证 (必需)
        constraint_result = self.constraint_validator.validate(diagnosis)
        
        # 2. 准确性验证 (可选)
        accuracy_result = None
        if ground_truth:
            accuracy_result = self.verifier.verify(diagnosis, ground_truth)
        
        # 3. 决策网关
        decision = self.gate.decide(
            constraint_result=constraint_result,
            accuracy_result=accuracy_result,
        )
        
        # 4. 生成报告
        return OrchestratorReport(
            scenario_id=diagnosis.scenario_id,
            overall_decision=decision.type,
            routing_decision=decision.routing,
            constraint_score=constraint_result.score,
            accuracy_score=accuracy_result.score if accuracy_result else None,
            # ... 其他字段
        )
```

---

## 报告生成系统

### 多格式输出

Expert Agent支持多种报告格式，以满足不同的使用场景：

#### 🎯 Markdown 格式 (默认)

**用途**: 用户展示、分享、打印、审计  
**优点**: 美观易读、支持表格和代码块、适合电子邮件

```python
# 生成Markdown报告
path = orchestrator.save_report(report)
# → /exports/expert_report_scenario_id_20260211_105525.md
```

**内容示例**:
```markdown
# Expert 诊断报告

**场景ID**: bgp_timeout_improvement_test  
**生成时间**: 2026-02-11T10:55:25.785891  

## 诊断决策

| 项目 | 值 |
|------|-----|
| **决策** | ACCEPT |
| **路由** | direct_user |
| **理由** | Constraint score 90.80% >= 85.00% |

## 诊断分数

| 指标 | 分数 | 说明 |
|------|------|------|
| 约束验证 (Task 4) | 90.8% | 幻觉检测、完整性检查 |
| 准确性验证 (Task 5) | N/A | 未提供Ground Truth |
| Expert置信度 | 94.0% | Expert Agent的置信度 |

## Expert诊断信息

### 根本原因 (Root Cause)
BGP TCP keepalive timeout on R1 due to network latency

### 解决方案 (Solution)
Increase TCP keepalive timer and restart BGP daemon

### 恢复命令 (Recovery Commands)
- `show running-config | include bgp`
- `systemctl restart bgp`
- `show ip bgp neighbor`

...
```

#### 📋 JSON 格式 (按需)

**用途**: API集成、自动化处理、数据库存储  
**优点**: 结构化、易于程序化处理、最小化存储

```python
# 生成JSON报告
path = orchestrator.save_report(report, report_format="json")
# → /exports/expert_report_scenario_id_20260211_105525.json
```

**内容示例**:
```json
{
  "scenario_id": "bgp_timeout_improvement_test",
  "timestamp": "2026-02-11T10:55:25.785891",
  "overall_decision": "accept",
  "routing_decision": {
    "target": "direct_user",
    "reason": "Diagnosis passed all validation gates",
    "requires_review": false
  },
  "constraint_score": 0.908,
  "accuracy_score": null,
  "confidence_score": 0.94,
  "critical_failures": [],
  "warnings": [],
  "improvement_suggestions": [],
  "execution_time_ms": 2.36
}
```

### save_report() 方法

```python
def save_report(
    self,
    report: OrchestratorReport,
    output_dir: Optional[Path] = None,
    report_format: str = "markdown",
) -> Path:
    """
    保存报告到文件
    
    参数:
        report: 要保存的OrchestratorReport
        output_dir: 输出目录 (默认./exports, 使用绝对路径)
        report_format: 格式类型 - 'markdown'(默认) 或 'json'
    
    返回:
        生成的文件路径
    
    示例:
        # 默认: Markdown格式
        path = orchestrator.save_report(report)
        # → exports/expert_report_scenario_id_20260211_105525.md
        
        # JSON格式
        path = orchestrator.save_report(report, report_format="json")
        # → exports/expert_report_scenario_id_20260211_105525.json
        
        # 自定义目录
        path = orchestrator.save_report(
            report,
            output_dir="/custom/path",
            report_format="markdown"
        )
    """
```

**文件命名规范**:
- 格式: `expert_report_{scenario_id}_{YYYYMMDD_HHMMSS}.{ext}`
- 示例: `expert_report_bgp_timeout_improvement_test_20260211_105525.md`
- 好处: 清晰标识 + 时间戳唯一性 + 支持多格式

### 报告内容详解

#### Markdown报告结构

```
1. 头部信息
   - 场景ID
   - 生成时间

2. 诊断决策表
   - 决策类型 (ACCEPT/FLAG/REJECT/ESCALATE)
   - 路由目标 (direct_user/review_queue/escalation)
   - 决策理由

3. 诊断分数表
   - 约束验证分数
   - 准确性验证分数 (若有)
   - Expert置信度

4. Expert诊断信息
   ├─ 根本原因 (Root Cause)
   ├─ 解决方案 (Solution)
   ├─ 恢复命令 (Recovery Commands)
   ├─ 验证步骤 (Verification Steps)
   └─ 证据 (Evidence)

5. 质量问题 (若有)
   ├─ 关键问题 (Critical Failures)
   ├─ 警告 (Warnings)
   └─ 改进建议 (Improvement Suggestions)

6. 执行信息
   - 执行时间
   - 生成时间戳
```

---

## 验证管道

### Task 4: 约束验证 (ExpertConstraintsValidator)

**目的**: 检测诊断中的幻觉和不完整性

```python
class ConstraintValidationResult:
    score: float              # 验证分数 [0, 1]
    passed: bool              # 是否通过 (score >= threshold)
    issues: List[str]         # 发现的问题
    root_cause_valid: bool    # RCA有效性
    solution_valid: bool      # 解决方案有效性
    commands_valid: bool      # 命令有效性
```

**验证项目**:

| 项目 | 检查内容 | 权重 |
|------|---------|------|
| **RCA有效性** | 根本原因是否具体明确 | 30% |
| **解决方案有效性** | 解决方案是否可实施 | 30% |
| **命令有效性** | 命令语法是否正确 | 20% |
| **完整性** | 是否包含所有必需信息 | 20% |

**使用**:

```python
validator = ExpertConstraintsValidator()
result = validator.validate(diagnosis)

print(f"Constraint Score: {result.score:.1%}")
print(f"Passed: {result.passed}")
print(f"Issues: {result.issues}")
```

### Task 5: 准确性验证 (DiagnosisVerifier)

**目的**: 与Ground Truth对比验证诊断正确性

```python
class AccuracyVerificationResult:
    score: float              # 准确性分数 [0, 1]
    matches: int              # 匹配项数
    total_items: int          # 总项数
    accuracy_details: dict    # 详细对比
```

**使用**:

```python
verifier = DiagnosisVerifier()
ground_truth = {
    "root_cause": "BGP TCP keepalive timeout",
    "solution": "Increase TCP keepalive timer",
    "commands": ["systemctl restart bgp"]
}

result = verifier.verify(diagnosis, ground_truth)
print(f"Accuracy: {result.score:.1%}")  # 89.0%
```

### 混合分数 (Hybrid Score)

结合约束验证和准确性验证的加权分数：

```
hybrid_score = (constraint_score × 0.6) + (accuracy_score × 0.4)
```

**分数区间**:
- **90-100%**: 极好 (Excellent) ✅
- **80-89%**: 很好 (Good) ✓
- **70-79%**: 中等 (Fair) ⚠️
- **60-69%**: 较差 (Poor) ❌
- **<60%**: 不合格 (Fail) ❌❌

---

## 决策路由

### DecisionType (决策类型)

```python
class DecisionType(str, Enum):
    ACCEPT = "accept"           # 接受诊断，直接返回用户
    FLAG = "flag"               # 标记问题，不返回
    REJECT = "reject"           # 拒绝诊断，生成新的
    ESCALATE = "escalate"       # 升级到高级专家
```

### RoutingDecision (路由决策)

```python
class RoutingTarget(str, Enum):
    DIRECT_USER = "direct_user"          # 直接返回用户
    REVIEW_QUEUE = "review_queue"        # 人工审核
    ESCALATION = "escalation"            # 升级处理
    AUTO_IMPROVEMENT = "auto_improvement" # 自动改进

class RoutingDecision(BaseModel):
    target: RoutingTarget              # 路由目标
    reason: str                        # 路由理由
    requires_review: bool              # 需要人工审核
    escalation_level: str              # 升级级别 (normal/urgent/critical)
```

### 决策网关 (DecisionGate)

```python
class DecisionGateConfig:
    constraint_threshold: float = 0.85     # 约束验证阈值
    accuracy_threshold: float = 0.80       # 准确性验证阈值
    hybrid_threshold: float = 0.82         # 混合分数阈值
    require_accuracy_verification: bool = False
    escalate_on_conflict: bool = True
    review_low_confidence: bool = True
    low_confidence_threshold: float = 0.75
```

**决策规则**:

```python
decision = self.gate.decide(
    constraint_result=constraint_result,
    accuracy_result=accuracy_result,
)

# 规则伪代码:
if constraint_score < threshold:
    decision = FLAG  # 约束失败，标记问题
elif accuracy_result and accuracy_score < threshold:
    decision = FLAG  # 准确性差，标记问题
elif confidence_score < low_confidence_threshold:
    decision = FLAG  # 信心低，需要审核
elif hybrid_score < hybrid_threshold:
    decision = ESCALATE  # 混合分数不达标，升级处理
else:
    decision = ACCEPT  # 所有检查通过，接受
```

---

## 使用示例

### 基础使用

```python
from src.olav.orchestrator.expert_orchestrator import (
    ExpertOrchestrator,
    ExpertDiagnosis,
    create_default_orchestrator
)

async def main():
    # 1. 创建Expert Orchestrator
    orchestrator = create_default_orchestrator()
    
    # 2. 获取Expert诊断 (来自Expert Agent)
    diagnosis = ExpertDiagnosis(
        scenario_id="bgp_timeout_issue",
        root_cause="BGP TCP keepalive timeout on R1",
        solution="Increase TCP keepalive timer and restart BGP daemon",
        recovery_commands=[
            "show running-config | include bgp",
            "systemctl restart bgp",
            "show ip bgp neighbor"
        ],
        verification_steps=[
            "Check BGP neighbor status",
            "Verify route convergence"
        ],
        evidence="BGP neighbor state changed from ESTABLISHED to IDLE"
    )
    
    # 3. 处理诊断 (验证 + 评分)
    report = await orchestrator.process(diagnosis)
    
    # 4. 保存报告
    md_path = orchestrator.save_report(report)  # Markdown (默认)
    json_path = orchestrator.save_report(report, report_format="json")  # JSON
    
    # 5. 检查决策
    print(f"决策: {report.overall_decision}")
    print(f"路由: {report.routing_decision.target}")
    print(f"约束分数: {report.constraint_score:.1%}")
    print(f"报告位置: {md_path}")
```

### 带准确性验证的使用

```python
async def main_with_verification():
    orchestrator = create_default_orchestrator()
    
    diagnosis = ExpertDiagnosis(...)
    
    # Ground Truth (参考答案)
    ground_truth = {
        "root_cause": "BGP TCP keepalive timeout",
        "solution": "Increase TCP keepalive timer",
        "commands": ["systemctl restart bgp"]
    }
    
    # 处理诊断 (包含准确性验证)
    report = await orchestrator.process(
        diagnosis,
        ground_truth=ground_truth  # 提供Ground Truth
    )
    
    print(f"约束分数: {report.constraint_score:.1%}")
    print(f"准确性分数: {report.accuracy_score:.1%}")
    print(f"混合分数: {report.hybrid_score:.1%}")
    
    # 保存报告
    path = orchestrator.save_report(report)
```

### 批量处理

```python
from typing import List

async def batch_process_diagnoses(
    diagnoses: List[ExpertDiagnosis]
) -> List[OrchestratorReport]:
    orchestrator = create_default_orchestrator()
    reports = []
    
    for diagnosis in diagnoses:
        report = await orchestrator.process(diagnosis)
        path = orchestrator.save_report(report)
        reports.append(report)
        print(f"✅ 已处理: {diagnosis.scenario_id} → {path}")
    
    return reports
```

---

## API参考

### OrchestratorReport

#### 方法

##### `to_markdown() -> str`

生成Markdown格式报告。

```python
report = await orchestrator.process(diagnosis)
markdown_text = report.to_markdown()
with open("report.md", "w") as f:
    f.write(markdown_text)
```

##### `to_json() -> str`

生成JSON格式报告。

```python
json_text = report.to_json()
print(json_text)  # JSON字符串
```

##### `model_dump(mode='json') -> dict`

导出为Python字典。

```python
data = report.model_dump(mode='json')
# 可传递给其他系统或存储到数据库
```

### ExpertOrchestrator

#### 初始化

```python
from src.olav.orchestrator.expert_orchestrator import ExpertOrchestrator
from src.olav.orchestrator.expert_orchestrator import (
    ExpertConstraintsValidator,
    DiagnosisVerifier,
    DecisionGateConfig
)

validator = ExpertConstraintsValidator()
verifier = DiagnosisVerifier()
config = DecisionGateConfig(
    constraint_threshold=0.85,
    accuracy_threshold=0.80,
    require_accuracy_verification=False
)

orchestrator = ExpertOrchestrator(
    constraint_validator=validator,
    verifier=verifier,
    gate_config=config
)
```

#### 方法

##### `process(diagnosis, ground_truth=None) -> OrchestratorReport`

处理诊断并生成验证报告。

**参数**:
- `diagnosis` (ExpertDiagnosis): Expert诊断
- `ground_truth` (dict, optional): Ground Truth数据

**返回**: OrchestratorReport

##### `save_report(report, output_dir=None, report_format='markdown') -> Path`

保存报告到文件。

**参数**:
- `report` (OrchestratorReport): 要保存的报告
- `output_dir` (Path, optional): 输出目录
- `report_format` (str): 格式类型 ('markdown' 或 'json')

**返回**: Path (保存的文件路径)

### 工厂函数

```python
from src.olav.orchestrator.expert_orchestrator import create_default_orchestrator

# 创建默认配置的Orchestrator
orchestrator = create_default_orchestrator()
```

---

## 最佳实践

### 1️⃣ 报告格式选择

| 场景 | 推荐格式 | 理由 |
|------|---------|------|
| 用户展示 | Markdown | 美观易读 |
| API集成 | JSON | 结构化处理 |
| 电子邮件 | Markdown | 支持格式化 |
| 数据库存储 | JSON | 规范化存储 |
| 打印或存档 | Markdown | 易于排版 |
| 自动化流程 | JSON | 易于解析 |

### 2️⃣ 错误处理

```python
from pathlib import Path

try:
    report = await orchestrator.process(diagnosis)
    path = orchestrator.save_report(report)
    print(f"✅ 报告已保存: {path}")
except Exception as e:
    print(f"❌ 错误: {e}")
    # 备用处理
```

### 3️⃣ 性能优化

```python
# ✅ 批量处理而不是逐个处理
reports = await batch_process_diagnoses(diagnoses_list)

# ✅ 异步处理
import asyncio
tasks = [orchestrator.process(d) for d in diagnoses]
reports = await asyncio.gather(*tasks)

# ✅ 避免重复验证
# 使用缓存机制存储已验证的诊断
```

### 4️⃣ 监控和日志

```python
import logging

logger = logging.getLogger(__name__)

report = await orchestrator.process(diagnosis)
logger.info(
    f"诊断完成",
    extra={
        "scenario_id": report.scenario_id,
        "decision": report.overall_decision.value,
        "constraint_score": report.constraint_score,
        "execution_time_ms": report.execution_time_ms
    }
)
```

### 5️⃣ 文件管理

```python
from pathlib import Path
import shutil

# 定期清理旧报告
exports_dir = Path.cwd() / "exports"
for report_file in exports_dir.glob("expert_report_*.md"):
    # 删除超过30天的文件
    if (datetime.now() - datetime.fromtimestamp(report_file.stat().st_mtime)).days > 30:
        report_file.unlink()

# 归档报告
archive_dir = Path.cwd() / "archives" / "2026-02"
archive_dir.mkdir(parents=True, exist_ok=True)
shutil.move(str(report_file), str(archive_dir))
```

### 6️⃣ 集成示例

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class DiagnosisRequest(BaseModel):
    root_cause: str
    solution: str
    recovery_commands: list[str]
    verification_steps: list[str]
    evidence: str

@app.post("/api/diagnose")
async def diagnose(req: DiagnosisRequest):
    """诊断端点"""
    orchestrator = create_default_orchestrator()
    
    diagnosis = ExpertDiagnosis(**req.dict())
    report = await orchestrator.process(diagnosis)
    
    # 返回JSON报告
    return report.model_dump(mode='json')

@app.post("/api/diagnose/export")
async def diagnose_and_export(req: DiagnosisRequest):
    """诊断并导出Markdown"""
    orchestrator = create_default_orchestrator()
    
    diagnosis = ExpertDiagnosis(**req.dict())
    report = await orchestrator.process(diagnosis)
    
    path = orchestrator.save_report(report)
    return {"report_path": str(path), "format": "markdown"}
```

---

## 故障排除

### 问题: 报告文件未生成

**原因**: 路径问题或权限不足

**解决**:
```python
from pathlib import Path

# 检查exports目录是否存在
exports_dir = Path.cwd() / "exports"
print(f"导出目录: {exports_dir.absolute()}")
print(f"目录存在: {exports_dir.exists()}")

# 创建目录
exports_dir.mkdir(parents=True, exist_ok=True)

# 检查写权限
print(f"可写: {os.access(exports_dir, os.W_OK)}")
```

### 问题: 约束验证分数过低

**原因**: 诊断不够完整或信息不准确

**解决**:
1. 检查诊断是否包含所有必需字段
2. 验证RCA (根本原因) 是否具体明确
3. 确保解决方案可实施
4. 检查恢复命令语法

```python
result = orchestrator.constraint_validator.validate(diagnosis)
print(f"问题: {result.issues}")
print(f"详情:")
print(f"  - RCA有效: {result.root_cause_valid}")
print(f"  - 解决方案有效: {result.solution_valid}")
print(f"  - 命令有效: {result.commands_valid}")
```

### 问题: 准确性分数与预期不符

**原因**: Ground Truth定义不准确或诊断偏离

**解决**:
1. 验证Ground Truth是否正确
2. 检查诊断是否匹配Ground Truth
3. 调整验证算法权重

```python
result = orchestrator.verifier.verify(diagnosis, ground_truth)
print(f"准确性: {result.score:.1%}")
print(f"匹配: {result.matches}/{result.total_items}")
print(f"详情: {result.accuracy_details}")
```

### 问题: 导出为空或格式错误

**原因**: 序列化问题

**解决**:
```python
# 验证数据完整性
print(report.model_dump())  # 检查所有字段

# 尝试导出为JSON
json_data = report.to_json()
print(len(json_data))  # 检查内容大小

# 尝试导出为Markdown
md_data = report.to_markdown()
print(md_data[:500])  # 显示开头
```

---

## 版本历史

### v1.0.0 (2026-02-11) ✅ 当前

**新功能**:
- ✅ 多格式报告输出 (Markdown/JSON)
- ✅ 改进的文件命名规范 (expert_report_*)
- ✅ 绝对路径处理，确保文件生成
- ✅ Markdown作为默认格式
- ✅ JSON按需可选

**改进**:
- ✅ 报告生成系统全面优化
- ✅ 路径处理更加可靠
- ✅ 用户体验改善

---

## 参考链接

- [ARCHITECTURE.md](ARCHITECTURE.md) - 系统整体架构
- [TESTING_QUICK_REFERENCE.md](TESTING_QUICK_REFERENCE.md) - 测试指南
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md) - Sub Agent开发
- [SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md) - Skill配置

---

**文档版本**: v1.0.0  
**最后更新**: 2026-02-11  
**维护者**: OLAV Development Team  
**状态**: ✅ 生产就绪
