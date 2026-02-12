# Deployment & Operations Guide

**版本**: v1.0.0  
**日期**: 2026-02-11  
**用途**: Expert Agent 系统部署和日常运维指南

---

## 前言

本指南涵盖 Expert Agent 系统从开发到生产的完整生命周期，包括：
- ✅ 部署检查清单
- ✅ 生产配置
- ✅ 监控和告警
- ✅ 故障排查
- ✅ 回滚程序

---

## 📋 部署前检查清单

### 代码检查 (30分钟)

```bash
# 1. 验证所有文件存在
✓ src/olav/testing/expert_constraints.py       (700+ 行)
✓ src/olav/testing/diagnosis_verifier.py       (600+ 行)
✓ src/olav/orchestrator/expert_orchestrator.py (740+ 行)
✓ src/olav/integration/expert_agent_integration.py (430+ 行)

# 2. 检查导入是否正确
python -c "from olav.testing.expert_constraints import ExpertConstraintsValidator"
python -c "from olav.testing.diagnosis_verifier import DiagnosisVerifier"
python -c "from olav.orchestrator import ExpertOrchestrator"
python -c "from olav.integration import QueryGuardIntegration"

# 3. 运行单元测试
pytest tests/unit/test_expert_constraints.py -v
pytest tests/unit/test_diagnosis_verifier.py -v
pytest tests/unit/test_orchestrator.py -v

# 4. 运行集成测试
pytest tests/integration/test_expert_integration.py -v
```

### 性能基准测试 (15分钟)

```python
import asyncio
import time
from olav.integration import create_staging_integration
from olav.testing.expert_constraints import ExpertDiagnosisOutput

async def benchmark():
    integration = create_staging_integration()
    
    # 单诊断性能
    diagnosis = ExpertDiagnosisOutput(...)
    
    start = time.time()
    for _ in range(100):
        await integration.process_expert_diagnosis(diagnosis)
    duration = time.time() - start
    
    per_diagnosis = duration / 100 * 1000  # ms
    print(f"✅ 单诊断: {per_diagnosis:.2f}ms (目标: <100ms)")
    
    # 批处理性能
    diagnoses = [diagnosis] * 10
    start = time.time()
    await integration.process_batch(diagnoses)
    duration = time.time() - start
    
    print(f"✅ 批处理(10): {duration*1000:.2f}ms (目标: <500ms)")

asyncio.run(benchmark())
```

预期结果：
```
✅ 单诊断: 45.32ms (目标: <100ms) √
✅ 批处理(10): 425.68ms (目标: <500ms) √
```

### 环境配置 (10分钟)

```bash
# 1. 检查必须的环境变量
printenv | grep -E "OLAV_|LLM_"

# 预期应该有:
OLAV_LOG_LEVEL=INFO
OLAV_DB_PATH=/path/to/main.duckdb

# 2. 验证数据库连接
python -c "
import duckdb
conn = duckdb.connect('$OLAV_DB_PATH')
print('✅ Database connection OK')
conn.close()
"

# 3. 检查磁盘空间 (最少 500MB)
df -h | grep -E "^/dev"

# 4. 验证文件权限
ls -l src/olav/integration/
# 预期: -rw-r--r--
```

### 依赖检查 (10分钟)

```bash
# 验证所有依赖已安装
pip list | grep -E "pydantic|duckdb|langgraph|langchain"

# 预期输出:
# pydantic                       2.0+
# duckdb                         0.9.0+
# langgraph                      0.1.0+
# langchain                      0.1.0+
```

**总预估时间**: 65分钟

---

## 🚀 生产部署步骤

### Step 1: 部署到测试环境 (30分钟)

```bash
# 1. 代码部署
cd /opt/expert-agent
git pull origin main
git log --oneline -5

# 2. 安装依赖
pip install -r requirements.txt --target ./lib

# 3. 运行集成测试
python -m pytest tests/integration/ -v --tb=short

# 4. 生成基准报告
python benchmark/baseline.py > reports/baseline_$(date +%Y%m%d).txt
```

### Step 2: 金丝雀部署 (2小时)

```python
# deployment/canary.py

from olav.integration import create_production_integration
from datetime import datetime

async def canary_deployment():
    """
    金丝雀部署: 对小部分流量进行测试
    """
    
    integration = create_production_integration()
    
    # 从测试数据集获取诊断
    test_diagnoses = load_test_diagnoses(count=100)
    
    # 处理 5% 流量
    canary_diagnoses = test_diagnoses[:5]
    
    results = await integration.process_batch(canary_diagnoses)
    metrics = integration.get_quality_metrics(results)
    
    # 检查关键指标
    assert metrics['pass_rate'] >= 0.70, "Pass rate too low"
    assert metrics['reject_rate'] <= 0.10, "Reject rate too high"
    assert metrics['critical_issues'] == 0, "Critical issues detected"
    
    log_deployment(
        stage="canary",
        timestamp=datetime.now(),
        metrics=metrics,
        status="success"
    )
    
    return metrics

# 运行
result = asyncio.run(canary_deployment())
print(f"✅ Canary deployment successful")
```

### Step 3: 逐步推送 (4小时)

```bash
# 时间表:
# 00:00 - 25% 流量
# 01:00 - 检查指标, 无问题则继续
# 01:30 - 50% 流量
# 02:30 - 检查指标, 无问题则继续
# 03:00 - 75% 流量
# 04:00 - 检查指标, 无问题则继续
# 04:30 - 100% 流量

# 监控脚本
watch -n 60 'curl http://localhost:8000/metrics/quality | jq .pass_rate'
```

---

## 📊 生产配置

### 生产 Orchestrator 配置

```python
# config/production.py

from olav.orchestrator import DecisionGateConfig, ExpertOrchestrator
from olav.testing.expert_constraints import ExpertConstraintsValidator

# 严格的生产标准
production_config = DecisionGateConfig(
    constraint_pass_threshold=0.90,      # 90% 才能直接通过
    confidence_pass_threshold=0.85,       # 85% 置信度
    accuracy_pass_threshold=0.85,         # 85% 准确度
    review_warning_threshold=0.75,        # 75% 以下升级
)

# 创建orchestrator
validator = ExpertConstraintsValidator()
orchestrator = ExpertOrchestrator(
    constraint_validator=validator,
    gate_config=production_config
)

# 预期决策分布 (基于历史数据):
# ✅ ACCEPT (60-70%): 直接用户，0-1秒
# ⚠️  REVIEW (15-20%): 人工审查，1-30分钟  
# ❌ REJECT (5-10%): 升级处理，即时
# 🔄 UNCERTAIN (2-5%): 重新分析，1-5分钟
```

### 队列配置

```python
# config/queues.py

from olav.integration import HumanReviewQueue, EscalationQueue

# 人工审查队列
review_queue = HumanReviewQueue(
    max_queue_size=1000,
    retention_days=7,  # 7天后自动删除
    alert_threshold=100,  # > 100 发送告警
)

# 升级队列
escalation_queue = EscalationQueue(
    max_queue_size=100,
    alert_immediately=True,  # 立即发送告警
    retention_days=30,  # 30天归档
)
```

### 监控和告警配置

```python
# config/monitoring.py

MONITORING_CONFIG = {
    # 质量指标告警
    "metrics": {
        "pass_rate_low": {
            "threshold": 0.50,  # 通过率 < 50%
            "severity": "critical",
            "action": "pause_deployment"
        },
        "reject_rate_high": {
            "threshold": 0.15,  # 拒绝率 > 15%
            "severity": "warning",
            "action": "alert_team"
        },
        "critical_issues": {
            "threshold": 1,  # > 0 关键问题
            "severity": "critical",
            "action": "immediate_escalation"
        }
    },
    
    # 队列告警
    "queues": {
        "review_queue_size": {
            "warning": 100,
            "critical": 500
        },
        "escalation_queue_size": {
            "warning": 10,
            "critical": 50
        },
        "queue_processing_time": {
            "threshold": 3600,  # 1 小时
            "unit": "seconds"
        }
    },
    
    # 性能告警
    "performance": {
        "diagnosis_latency": {
            "p50": 50,  # ms
            "p99": 200,  # ms
            "threshold": 500,  # 告警值
        },
        "batch_latency": {
            "p50": 400,  # 10诊断
            "p99": 800,
            "threshold": 1500,
        }
    }
}
```

---

## 🔍 监控

### 实时监控仪表板

```python
# monitoring/dashboard.py

import asyncio
from datetime import datetime, timedelta

class RealtimeDashboard:
    def __init__(self, integration):
        self.integration = integration
        self.start_time = datetime.now()
    
    async def update(self):
        """每30秒更新一次"""
        while True:
            # 获取最近1小时数据
            recent_start = datetime.now() - timedelta(hours=1)
            diagnoses = get_diagnoses_since(recent_start)
            
            results = await self.integration.process_batch(diagnoses)
            metrics = self.integration.get_quality_metrics(results)
            
            # 显示仪表板
            self._display_dashboard(metrics)
            
            await asyncio.sleep(30)
    
    def _display_dashboard(self, metrics):
        """显示格式化的仪表板"""
        
        uptime = datetime.now() - self.start_time
        uptime_str = f"{uptime.total_seconds()//3600:.0f}h {uptime.total_seconds()%3600//60:.0f}m"
        
        dashboard = f"""
╔════════════════════════════════════════════════════════════════╗
║             EXPERT AGENT QUALITY DASHBOARD                     ║
╠════════════════════════════════════════════════════════════════╣
║ Uptime: {uptime_str:50}║
║                                                                ║
║ Last Hour Metrics:                                             ║
║   📊 Total Processed:  {metrics['total_processed']:4}                           ║
║   ✅ ACCEPT:          {metrics['accept_count']:4} ({metrics['pass_rate']:5.1%})                    ║
║   ⚠️  REVIEW:         {metrics['review_count']:4} ({metrics['review_rate']:5.1%})                    ║
║   ❌ REJECT:          {metrics['reject_count']:4} ({metrics['reject_rate']:5.1%})                    ║
║   🔄 UNCERTAIN:       {metrics['uncertain_count']:4} ({metrics['uncertain_rate']:5.1%})                    ║
║                                                                ║
║ Quality Scores:                                                ║
║   Avg Constraint:     {metrics['avg_constraint_score']:.2%}                          ║
║   Avg Confidence:     {metrics['avg_confidence_score']:.2%}                          ║
║   Critical Issues:    {metrics['critical_issues']:4}                            ║
║                                                                ║
║ Queue Status:                                                  ║
║   Review Queue:       {self._review_queue_size():4}                            ║
║   Escalation Queue:   {self._escalation_queue_size():4}                            ║
╚════════════════════════════════════════════════════════════════╝
        """
        
        print(dashboard)
        
        # 检查告警
        self._check_alerts(metrics)
    
    def _check_alerts(self, metrics):
        """检查是否需要告警"""
        
        alerts = []
        
        # 通过率太低
        if metrics['pass_rate'] < 0.50:
            alerts.append("🚨 CRITICAL: Pass rate < 50%")
        
        # 拒绝率太高
        if metrics['reject_rate'] > 0.15:
            alerts.append("⚠️  WARNING: Reject rate > 15%")
        
        # 关键问题
        if metrics['critical_issues'] > 0:
            alerts.append(f"🚨 CRITICAL: {metrics['critical_issues']} critical issues")
        
        # 显示告警
        for alert in alerts:
            print(f"\n{alert}")
            send_alert(alert)
```

### 关键指标

```python
# monitoring/metrics.py

CRITICAL_METRICS = {
    # 1. 通过率 (核心指标)
    "pass_rate": {
        "description": "通过约束检查的诊断比例",
        "target": ">= 70%",
        "warning": "< 60%",
        "critical": "< 50%",
        "impact": "服务可用性"
    },
    
    # 2. 拒绝率 (安全指标)
    "reject_rate": {
        "description": "检测到问题而拒绝的诊断比例",
        "target": "< 10%",
        "warning": "> 12%",
        "critical": "> 15%",
        "impact": "错误诊断防护"
    },
    
    # 3. 平均约束得分 (质量指标)
    "avg_constraint_score": {
        "description": "平均约束检查得分",
        "target": ">= 85%",
        "warning": "< 75%",
        "critical": "< 60%",
        "impact": "诊断质量"
    },
    
    # 4. 置信度 (可靠性指标)
    "avg_confidence_score": {
        "description": "Expert Agent 平均置信度",
        "target": ">= 85%",
        "warning": "< 75%",
        "critical": "< 60%",
        "impact": "诊断可靠性"
    },
    
    # 5. 关键问题 (安全指标)
    "critical_issues": {
        "description": "检测到的关键问题数量",
        "target": "= 0",
        "warning": "> 0",
        "critical": "> 1",
        "impact": "系统安全"
    },
    
    # 6. 队列大小 (运维指标)
    "review_queue_size": {
        "description": "待人工审查诊断数",
        "target": "< 50",
        "warning": "50-100",
        "critical": "> 100",
        "impact": "人工处理能力"
    },
    
    # 7. 处理延迟 (性能指标)
    "p99_latency": {
        "description": "99分位数处理延迟",
        "target": "< 150ms",
        "warning": "150-300ms",
        "critical": "> 300ms",
        "impact": "用户响应时间"
    }
}
```

---

## 🔧 故障排查

### 问题: 通过率突然下降

```
症状: Pass rate 从 75% 降到 40%
时间: 2026-02-11 14:30

调查步骤:
```

```python
# 1. 检查最近的诊断
recent_diagnoses = get_diagnoses_since(datetime.now() - timedelta(minutes=30))

# 2. 分析问题类型
for diagnosis in recent_diagnoses:
    result = await integration.process_expert_diagnosis(diagnosis)
    if result['decision'] != 'accept':
        print(f"Problem: {result['report'].reason}")
        print(f"Evidence: {result['report'].critical_failures}")

# 3. 检查是否是Expert Agent问题
avg_confidence = sum(d.confidence_score for d in recent_diagnoses) / len(recent_diagnoses)
if avg_confidence < 0.70:
    print("❌ Expert Agent confidence too low - check model/prompts")

# 4. 检查约束检查器
constraint_failures = defaultdict(int)
for diagnosis in recent_diagnoses:
    report = validator.validate(diagnosis)
    for failure in report.failed_checks:
        constraint_failures[failure] += 1

print("Failed constraints:", dict(constraint_failures))
```

### 问题: 队列堆积

```
症状: Review queue 有 500+ 项目
原因: 人工审查人员不足或系统变慢

解决:
```

```python
# 1. 分析为什么送审查
queue_reasons = defaultdict(int)
for item in review_queue.get_all():
    queue_reasons[item['reason']] += 1

# 2. 自动处理可以处理的
for reason, count in queue_reasons.items():
    if reason == "low_confidence" and count > 10:
        # 自动重新分析低置信度项目
        await auto_reanalyze_low_confidence()

# 3. 通知团队处理
notify_team(f"Review queue: {len(review_queue)} items. "
            f"Top reason: {max(queue_reasons, key=queue_reasons.get)}")
```

### 问题: 性能降级

```
症状: 诊断处理时间从 50ms → 300ms
原因: 可能是数据库变慢或内存泄漏

调查:
```

```bash
# 1. 检查数据库性能
sqlite3 .olav/db/main.duckdb ".timer on"
SELECT COUNT(*) FROM diagnoses;

# 2. 检查内存使用
ps aux | grep "python.*expert"
# 每小时内存增长 > 100MB 是泄漏信号

# 3. 检查进程数
ps aux | grep "python.*expert" | wc -l

# 4. 重启服务
systemctl restart expert-agent
```

---

## ↩️ 回滚程序

### 需要回滚的情况

- ❌ Pass rate < 50%
- ❌ 关键问题数 > 2
- ❌ 内存泄漏（每小时 > 200MB 增长）
- ❌ 崩溃或无响应

### 回滚步骤

```bash
#!/bin/bash
# rollback.sh

set -e

echo "=== Expert Agent Rollback ==="

# 1. 停止服务
echo "1. Stopping service..."
systemctl stop expert-agent

# 2. 恢复代码
echo "2. Reverting code..."
git log --oneline | head -10
# 选择上一个稳定版本
git checkout v1.0.0-stable

# 3. 清除缓存
echo "3. Clearing caches..."
rm -rf src/olav/__pycache__
rm -rf .pytest_cache

# 4. 重启服务
echo "4. Restarting service..."
systemctl start expert-agent

# 5. 验证
echo "5. Verifying..."
sleep 5
curl -s http://localhost:8000/health | jq .status

if [ "$?" -eq 0 ]; then
    echo "✅ Rollback successful"
else
    echo "❌ Rollback failed"
    exit 1
fi
```

---

## 📈 SLA 指标

```
服务等级协议 (SLA):

1. 可用性 (Availability)
   目标: 99.9%
   监测: 每天检查至少 1000 个诊断
   
2. 准确性 (Accuracy)
   目标: >= 90% 通过率
   监测: 每小时质量检查

3. 延迟 (Latency)
   目标: P99 < 150ms
   监测: 实时性能监控

4. 可靠性 (Reliability)
   目标: 0 关键问题
   监测: 实时关键问题计数

5. 支持 (Support)
   目标: 队列处理时间 < 30分钟
   监测: 队列监控
```

---

## ✅ 部署检查清单

### 部署前

- [ ] 所有单元测试通过
- [ ] 性能基准 OK (< 100ms/诊断)
- [ ] 无关键代码问题
- [ ] 文档已更新
- [ ] 团队已培训

### 部署时

- [ ] 金丝雀部署 (5% 流量)
- [ ] 监控所有关键指标
- [ ] 团队待命
- [ ] 回滚计划已就位

### 部署后

- [ ] 检查 24 小时的指标
- [ ] 通过率 >= 70%
- [ ] 无关键问题
- [ ] 队列大小正常
- [ ] 性能满足 SLA

---

**版本**: v1.0.0  
**完成日期**: 2026-02-11  
**状态**: ✅ 生产就绪
