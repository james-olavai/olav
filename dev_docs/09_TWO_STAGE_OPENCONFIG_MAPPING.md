# OpenConfig 两阶段映射策略

**日期**: 2026-03-21  
**版本**: v1.0  
**作者**: Phase 3 Closure Loop  
**目标**: 加速 OpenConfig 字段映射从 49.80% → 90%+

---

## 1. 问题分析

### 当前状态
- **当前覆盖率**: 49.80% (5,220/10,482 fields)
- **目标覆盖率**: 90.00% (~9,433 fields)
- **缺口**: 40.20% (4,213 fields)
- **执行速度**: Batch 1-5 花费大量LLM API调用（且Batch 3因字段名不匹配失效）

### 瓶颈
1. **LLM成本高**: 每个字段都需要API调用
2. **精度不稳定**: 字段名差异大（`vrf` vs `network_instance`）导致映射质量波动
3. **缺乏快速通道**: 没有区分"高相似度"和"低相似度"候选

---

## 2. 两阶段策略设计

### 📊 Stage 1: Embedding 快速映射

**目的**: 通过语义相似度搜索快速识别高序相似的字段→路径映射

**成本**: 极低（本地embedding，无API调用）

**流程**:
```
Step 1: 对所有 OpenConfig YANG 路径做embedding向量化
        Cost: O(n) - 一次性离线计算
        
Step 2: 对每个未映射字段做embedding
        Cost: O(1) per field - 向量化 + 余弦相似度搜索
        
Step 3: 按相似度排序，返回 Top-K 候选
        
Step 4: 置信度决策
        - similarity >= 0.80 → 直接应用 ✅ (无需LLM)
        - 0.60 <= similarity < 0.80 → 进入Stage 2
        - similarity < 0.60 → 低优先级，LLM fallback
```

**效果预期**:
- 快速覆盖 40-50% 的剩余字段
- 0 额外API成本
- 处理速度 ~1000 fields/sec (本地embedding)

**关键参数**:
```python
# openconfig_embedding_fast_mapping.py
confidence_threshold_auto = 0.80      # 直接应用阈值
confidence_threshold_uncertain = 0.60  # Stage 2 候选阈值
top_k = 5                             # 返回Top-5候选给LLM验证
```

---

### 🧠 Stage 2: LLM 精确映射

**目的**: 对Stage 1的中等置信度候选做精确验证，覆盖剩余 10-15% 的字段

**成本**: 仅对 ~20% 的字段调用LLM（相比全量40% 的API节省）

**流程**:
```
Workflow A - 验证 (Embedding 找到了候选)
  LLM 任务: "从这5个候选中选最好的，并评分"
  Cost: 50-100 tokens per field
  Output: 精确选择 + confidence score

Workflow B - 生成 (Embedding 未找到候选)
  LLM 任务: "根据字段名和命令，生成OpenConfig路径"
  Cost: 150-200 tokens per field
  Output: 新映射 + confidence score
```

**效果预期**:
- 额外覆盖 10-15% 字段
- LLM调用数 = uncertain count (~20% of gaps) = ~850 个
- 相比Batches 1-5的10,000+ API调用，节省 85%+

**关键改进**:
1. LLM 作为 **验证器** 而非 **生成器**（当有候选时）
2. 结合 embedding 的候选提高准确率
3. 优先处理高优先级字段（Workflow A）

---

## 3. 实施脚本

### 脚本1: `openconfig_embedding_fast_mapping.py`
```bash
cd /home/yhvh/Olav
python scripts/openconfig_embedding_fast_mapping.py
```

**输出**:
```
exports/embedding_stage1_results_20260321_HHMMSS.json
├── auto_mapped: 2000+ (confidence >= 0.80)
├── uncertain:   1500+ (confidence 0.60-0.80)  
└── low_confidence: 1000+ (confidence < 0.60)
```

### 脚本2: `openconfig_llm_stage2_precision.py`
```bash
python scripts/openconfig_llm_stage2_precision.py \
    exports/embedding_stage1_results_20260321_HHMMSS.json
```

**输入**: Stage 1 结果文件  
**输出**:
```
exports/llm_stage2_results_20260321_HHMMSS.json
├── verified_approved:   800+ (LLM-ranked embedding candidates)
├── verified_uncertain:  700  (需人工审核)
├── generated_approved:  200+ (LLM新增映射)
└── generated_uncertain: 200  (需人工审核)
```

### 脚本3: `openconfig_two_stage_mapping.py` (完整管道)
```bash
# 一键运行 Stage 1 + Stage 2 + 应用结果 + 审计
python scripts/openconfig_two_stage_mapping.py
```

**自动执行**:
1. ✅ Stage 1: Embedding 快速映射
2. ✅ Stage 2: LLM 精确映射 (verify_max=200, generate_max=100)
3. ✅ 应用所有approved mappings到 schema_catalog
4. ✅ 重新审计覆盖率

**输出**:
```
exports/two_stage_pipeline_report_20260321_HHMMSS.json
{
  "stage1": {"auto_mapped": 2000, "uncertain": 1500, ...},
  "stage2": {"verified_approved": 800, "generated_approved": 200, ...},
  "application": {"total_applied": 3000, ...},
  "audit": {
    "coverage_before": 49.80%,
    "coverage_after": 62.15%,  # 例子
    "delta_percent": 12.35%,
    "gap_to_90_percent": 27.85%
  }
}
```

---

## 4. 预期效果 vs 现有方法

### 质量对比

| 指标 | 旧方法 (Batch 1-5) | 新方法 (Stage 1+2) |
|------|-----|-----|
| 执行模式 | 全量LLM生成 | Embedding + LLM混合 |
| API调用数 | ~10,000 (all gaps) | ~1,000 (20% gaps) |
| 执行时间 | 2-3 小时 | 15-20 分钟 |
| 精度 | 72-78% (confidence 0.71-0.78) | 80-88% (embedding 0.80+) |
| 成本 | $5-10 (OpenRouter) | $0.50-1 |
| 易扩展性 | 低（每个gap都要LLM） | 高（embedding可并行） |

### 覆盖率改善路径

```
Current:           49.80%  (5,220/10,482)
├─ After Stage 1:  62.00% (~6,500/10,482)   [+850-900 from embedding]
├─ After Stage 2:  72.00% (~7,550/10,482)   [+300-400 from LLM verify]
├─ Additional LLM:  85.00% (~8,900/10,482)  [+500+ from LLM generate on uncertain]
└─ Manual review:   90%+  (~9,433/10,482)   [+500+ from human]
```

---

## 5. 使用指南

### 快速开始

```bash
# Step 1: 确保embedding模型可用
python -c "from olav.core.embedder import get_embedder; e = get_embedder(); print(f'✓ Embedder ready: {e}')"

# Step 2: 运行完整两阶段管道
python scripts/openconfig_two_stage_mapping.py

# 查看结果
cat exports/two_stage_pipeline_report_*.json | jq '.improvement'
```

### 自定义配置

```python
# openconfig_two_stage_mapping.py 的 main() 函数

# 调整Stage 1置信度阈值
stage1_results = run_embedding_mapping(
    confidence_threshold_auto=0.75,      # 降低阈值 → 更多auto-mapped
    confidence_threshold_uncertain=0.55  # 降低下限 → 更多进入Stage 2
)

# 调整Stage 2处理量
stage2_results = run_stage2_llm_precision(
    verify_max=500,     # 处理更多uncertain
    generate_max=200    # 生成更多新映射
)
```

### 分步执行（用于调试）

```bash
# 只运行Stage 1
python scripts/openconfig_embedding_fast_mapping.py
# 查看 auto_mapped 和 uncertain 的分布

# 只运行Stage 2（使用上一步的结果）
python scripts/openconfig_llm_stage2_precision.py \
    exports/embedding_stage1_results_20260321_HHMMSS.json \
    --verify-max 100        # 限制数量调试
    
# 手动应用（观察结果）
# 运行 python scripts/openconfig_two_stage_mapping.py 中的 apply_mappings_to_catalog()
```

---

## 6. 与现有方法的兼容性

**Batch 1-5 的作用**:
- 已实现的Batch 1-5继续保留，可共存
- Stage 1-2 会处理 Batch 1-5 未覆盖的字段

**何时使用哪个方法**:
| 场景 | 推荐方法 |
|------|---------|
| 缺口初始快速处理（40-50%） | ✅ Stage 1 (embedding) |
| 半确定候选验证 | ✅ Stage 2 (LLM verify) |
| 完全新增字段的生成 | ✅ Batch X (纯LLM) |
| 人工精细调整 | 📋 Manual review |

---

## 7. 下一步行动

### Phase 3 Gate通过路径

```
Current (49.80%)
├─ Run Stage 1+2 pipeline     → ~65-70%
├─ Batch 6+ 补充               → ~80%+
├─ Human review & patch       → ~90%+
└─ Phase 3 gate PASS ✅
```

### 推荐执行顺序

1. **立即执行**
   - [ ] 运行 `openconfig_two_stage_mapping.py`
   - [ ] 审视结果覆盖率改善
   - [ ] 更新 tracking.md ADJ Entry

2. **并行进行**
   - [ ] Stage 2 uncertain 结果人工审核
   - [ ] Batch 6+ 字段定义生成（用纯LLM或手工）

3. **重复迭代**
   - [ ] 降低embedding置信度阈值 (0.80 → 0.70) 继续提升
   - [ ] 增加 Stage 2 LLM处理量
   - [ ] 最终手工review完成到90%

---

## 8. 技术细节

### Embedding 模型
```python
# from olav.core.embedder.py
default_model = "nvidia/NV-Embed-v2"  # 或配置中的值
device = "cuda" if available else "cpu"
dimension = 768 / 1024  # 取决于模型
normalization = True    # 用于cosine相似度
```

### LLM 调用模式

**Stage 2A - 验证模式**:
```
Input: field_name="vrf", candidates=[list of paths]
Prompt: "Select the best OpenConfig path from these 5 candidates"
Output: {"selected_path": "...", "confidence": 0.85, "reasoning": "..."}
```

**Stage 2B - 生成模式**:
```
Input: field_name="vrf", platform="cisco_ios", command="show vrf"
Prompt: "Generate the best OpenConfig YANG path for this field"
Output: {"openconfig_path": "...", "confidence": 0.75, "reasoning": "..."}
```

---

## 9. 故障排除

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| ImportError: embedder | 依赖未安装 | `uv pip install sentence-transformers` |
| Embedding太慢 | GPU不可用 | 设置 `device='cpu'` 或用GPU |
| LLM API错误 | 速率限制或模型不可用 | 降低 verify_max/generate_max |
| 应用失败 | 字段名不匹配 | 检查 schema_catalog 实际字段名 |
| 覆盖率没改善 | 候选质量差 | 降低相似度阈值重试 |

---

## 10. 参考

- **相关文档**: `dev_docs/07. OPENCONFIG_SCHEMA_DESIGN.md`
- **当前状态**: `dev_docs/01. tracking.md` ADJ Entry #8
- **执行脚本**: 
  - `scripts/openconfig_embedding_fast_mapping.py`
  - `scripts/openconfig_llm_stage2_precision.py`
  - `scripts/openconfig_two_stage_mapping.py`

