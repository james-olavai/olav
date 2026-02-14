# TextFSM Agent 架构分析 & 优化空间

**日期:** 2026-02-07 | **作者:** Architecture Analysis
**当前版本:** v0.9.8 | **基线成功率:** <40% → 70-85% (with NTC)

---

## 1. 现有架构概览

### 当前流程

```
generate_node → test_node → [条件判断]
                              ├→ success (80%+) → END
                              └→ analyze_node → generate_node (loop)
```

### 当前节点的职责

| 节点 | 职责 | 输出 |
|------|------|------|
| **generate** | 用LLM生成TextFSM模板 | template (string) |
| **test** | 用样本输出测试模板 | test_results (success/fail count) |
| **analyze** | 分析失败原因 | error_message (字符串反馈) |

---

## 2. 架构级别的问题分析

### 问题 1️⃣: **信息丢失in Analyze节点**

**现象:**
```python
# analyze_node 中
response = await llm.ainvoke(messages)
state.error_message = f"Iteration {state.iteration}: {response.content[:200]}"
```

**问题:**
- LLM分析的详细反馈只保存为字符串
- 下一次generate_node 收不到结构化的错误信息
- `_build_generation_prompt()` 并未使用analyze的结果来调整prompt

**影响:**
- 即使3次迭代失败原因不同，generate node也用同样的prompt生成
- 无法实现"针对性改进"(targeted improvement)

### 问题 2️⃣: **缺少错误模式识别**

**现象:**
连续3次迭代可能都失败，但失败原因完全不同：
- Iter 1: Missing Value definitions
- Iter 2: Wrong state transitions  
- Iter 3: Incorrect filldown usage

**问题:**
- 系统没识别出"这个命令的输出结构复杂，需要不同策略"
- 所有迭代都用固定的生成策略

**影响:**
- 盲目重复失败的操作
- 无法自适应调整难度

### 问题 3️⃣: **二元成功判断，缺少梯度评估**

**现象:**
```python
# test_node 中
if success_rate >= 0.8:  # 非黑即白
    state.status = "success"
else:
    # 没有记录 45% vs 70% 的区别
```

**问题:**
- 只有"成功"和"失败"两个状态
- 45%成功率的模板和70%成功率的模板待遇相同（都是失败）
- 系统无法评估"部分正确"的模板的价值

**影响:**
- 每次迭代都在地板摩擦(接近0%)和天花板(>80%)之间
- 无法识别"已有70%正确，只需要微调"的情况

### 问题 4️⃣: **静态NTC匹配，缺少智能选择**

**现象:**
```python
def _get_ntc_reference(platform: str, command: str) -> str:
    matches = list(ntc_root.glob(pattern))
    # 只返回前2个，没有评分
    for template_file in templates_found[:2]:
        ...
```

**问题:**
- Glob pattern匹配多个结果，只取前2
- 没有评估"哪个NTC模板最相关"
- 对于相同平台，可能存在10+个候选，随机选择

**影响:**
- 有时给LLM参考了完全不相关的模板
- NTC库的优势没完全发挥

### 问题 5️⃣: **没有输出结构的形式化验证**

**现象:**
```python
def _test_template(template: str, output: str):
    try:
        fsm = textfsm.TextFSM(template)
        return fsm.ParseText(output)
    except Exception:
        return None
```

**问题:**
- 只检查"能否解析"(syntactic correctness)
- 不检查"解析结果是否有意义"(semantic correctness)
- 例如：可能生成了语法正确但Value为0的垃圾模板

**影响:**
- 虚假的"成功"（模板语法对，但没捕获任何数据）
- 无法区分"成功但不完整"

### 问题 6️⃣: **缺少降级策略(Fallback)**

**现象:**
- 3次迭代都失败 → 返回空模板或最后一个模板
- 没有"简化策略"

**问题:**
- 复杂命令（如`show route summary`)可能永远无法生成完美模板
- 系统应该能退而求其次，生成"80%正确"的模板

**影响:**
- 全有或全无的结果
- 实际应用中更需要"不完美但可用"的模板

### 问题 7️⃣: **缺少跨迭代学习**

**现象:**
- 每个generate_node都是独立调用LLM，无记忆
- 即使前2次都失败在"State transitions"，第3次仍可能犯同样错误

**问题:**
- LLM每次都从零开始生成
- 没有"历史约束"(constraints from previous attempts)

**影响:**
- 低效的迭代
- 容易陷入重复失败的循环

---

## 3. 架构改进方案

### 改进 1️⃣: **结构化错误分析与反馈传播**

**方案:**

```python
@dataclass
class ErrorAnalysis:
    """结构化的错误分析结果"""
    error_category: Literal[
        "value_missing",           # Values定义不完整
        "state_transition",        # 状态转移错误
        "regex_pattern",           # 正则表达式不匹配
        "filldown_usage",          # Filldown用法错误
        "output_format",           # 输出格式假设错误
        "unknown"
    ]
    confidence: float              # 0-1, 置信度
    specific_issue: str            # 具体问题描述
    suggested_fix: str             # 建议修复方案
    affected_lines: list[int]     # 模板中有问题的行

# 在TextfsmState中增加
@dataclass
class TextfsmState:
    ...
    error_analysis: ErrorAnalysis | None = None  # 新增
    failed_attempts: list[tuple[str, ErrorAnalysis]] = field()  # 新增：历史失败记录
```

**新的Analyze流程:**

```python
async def analyze_node(state: TextfsmState) -> TextfsmState:
    # 步骤1: 结构化分析失败原因
    analysis = await _analyze_failure_structured(
        state.template,
        state.test_results,
        state.raw_output
    )
    state.error_analysis = analysis
    
    # 步骤2: 记录失败历史
    state.failed_attempts.append((state.template, analysis))
    
    # 步骤3: 根据失败模式调整策略
    state.generation_strategy = _select_strategy(
        state.failed_attempts,  # 看是否重复出现同类错误
        state.iteration
    )
    
    return state
```

**优势:**
- ✅ Generate node现在能收到结构化反馈，而非模糊字符串
- ✅ 能识别"值缺失"vs"状态转移"这样不同的问题
- ✅ 可以针对性修改prompt策略

---

### 改进 2️⃣: **多维度质量评分，而非二元判断**

**方案:**

```python
@dataclass
class TemplateQuality:
    """多维度质量评估"""
    syntax_valid: bool              # 语法是否正确
    parse_success_rate: float       # 0-1, 能成功解析的输出比例
    
    # 语义质量指标
    value_extraction_coverage: float  # 捕获的Value比例
    regex_accuracy: float            # 正则匹配准确度
    state_completeness: float        # 状态机完整性
    
    overall_score: float            # 加权综合评分 0-100
    quality_tier: Literal["invalid", "minimal", "partial", "good", "excellent"]
    
    # 细节反馈
    missing_values: list[str]       # 该捕获但没捕获的数据
    extra_noise: list[str]          # 捕获了不该捕获的数据
```

**测试节点改进:**

```python
async def test_node(state: TextfsmState) -> TextfsmState:
    ...
    # 而不仅是 success/failed count
    quality = await _evaluate_template_quality(
        state.template,
        parsed_results,
        state.raw_output
    )
    state.template_quality = quality
    
    # 条件判断改为梯度
    if quality.overall_score >= 85:
        state.status = "success"
    elif quality.overall_score >= 70:
        state.status = "partial_success"  # 新增
        # 标记可以做微调迭代
    else:
        state.status = "failed"
    
    return state
```

**优势:**
- ✅ 能区分70%成功和45%成功的本质差别
- ✅ 部分成功的模板可以"微调"而非"重写"
- ✅ 可以做出更智能的继续/停止决策

---

### 改进 3️⃣: **动态策略选择与递增难度**

**方案:**

```python
class GenerationStrategy(Enum):
    """生成策略"""
    FULL_GENERATION = 1      # 完全重新生成
    TARGETED_FIX = 2         # 修复特定问题部分
    SIMPLIFICATION = 3       # 简化模板结构
    COMPONENT_REBUILD = 4    # 逐组件重建（Values→States→Transitions）

async def generate_node(state: TextfsmState) -> TextfsmState:
    ...
    # 根据失败历史选择策略
    if not state.failed_attempts:
        strategy = GenerationStrategy.FULL_GENERATION
    else:
        # 分析失败模式
        error_patterns = _extract_error_patterns(state.failed_attempts)
        
        if _is_same_error_repeating(error_patterns):
            # 反复失败 → 简化模板
            strategy = GenerationStrategy.SIMPLIFICATION
        elif len(state.failed_attempts) >= 2:
            # 有多个不同错误 → 微调修复
            strategy = GenerationStrategy.TARGETED_FIX
        else:
            strategy = GenerationStrategy.FULL_GENERATION
    
    # 根据策略选择Prompt
    prompt = _build_generation_prompt(
        state.raw_output,
        state.command_name,
        state.platform,
        strategy=strategy,
        error_context=state.error_analysis,
        failed_attempts=state.failed_attempts
    )
    ...
```

**优势:**
- ✅ 自适应不同复杂度的命令
- ✅ 避免无效重复
- ✅ 实现递进式优化而非随机重试

---

### 改进 4️⃣: **智能NTC模板选择**

**方案:**

```python
async def _get_ntc_reference_intelligent(
    platform: str,
    command: str,
    raw_output: str,
    count: int = 2
) -> list[tuple[str, str]]:  # [(template_path, template_content), ...]
    """
    智能选择最相关的NTC模板
    
    策略:
    1. 先用精确匹配 (exact command name)
    2. 再用语义相似度 (similarity to output characteristics)
    3. 最后用模板流行度 (number of fields extracted)
    """
    
    # 步骤1: 收集候选
    candidates = _glob_ntc_templates(platform, command)
    
    if not candidates:
        return []
    
    # 步骤2: 针对每个候选评分
    scores = []
    for template_path in candidates:
        score = _score_template_relevance(
            template_path,
            command,
            raw_output  # 用实际输出特征来评分
        )
        scores.append((template_path, score))
    
    # 步骤3: 按评分排序，返回top N
    scores.sort(key=lambda x: x[1], reverse=True)
    return [
        (path, path.read_text())
        for path, _ in scores[:count]
    ]

def _score_template_relevance(
    template_path: Path,
    command: str,
    raw_output: str
) -> float:
    """评估模板与当前任务的相关性"""
    
    score = 0.0
    
    # 因素1: 命令名称匹配度(权重30%)
    cmd_similarity = _string_similarity(
        template_path.stem.lower(),
        command.lower()
    )
    score += cmd_similarity * 0.3
    
    # 因素2: 输出特征匹配(权重50%)
    #       - 输出中出现的值是否被template定义了？
    template_content = template_path.read_text()
    values_in_template = _extract_values(template_content)
    patterns_in_output = _extract_output_patterns(raw_output)
    feature_match = _calculate_feature_overlap(
        values_in_template,
        patterns_in_output
    )
    score += feature_match * 0.5
    
    # 因素3: 模板质量(权重20%)
    #       - Value个数(越多越好), 行数(适中)
    quality = _estimate_template_quality(template_content)
    score += quality * 0.2
    
    return score
```

**优势:**
- ✅ NTC引用不再是随机的，而是针对性的
- ✅ 用实际输出特征来评选最相关的模板
- ✅ 提高NTC库的实际利用效率

---

### 改进 5️⃣: **输出结构的形式化验证**

**方案:**

```python
@dataclass
class ParseQualityMetrics:
    """解析质量指标"""
    # 覆盖率
    successful_parses: int
    failed_parses: int
    parse_success_rate: float
    
    # 有意义性检查
    avg_values_extracted: float   # 平均每行提取多少个Value
    zero_value_rate: float        # 多少行的所有Value都是空的
    
    # 一致性检查
    value_consistency: dict[str, float]  # 每个Value的填充率
    
    # 完整性评估
    estimated_coverage: float  # 估计捕获了多少有用的数据

async def _validate_template_semantically(
    template: str,
    outputs: list[str],
    raw_output: str
) -> ParseQualityMetrics:
    """
    不仅检查语法，还检查语义质量
    """
    import textfsm
    
    fsm = textfsm.TextFSM(template)
    values_defined = fsm.header
    
    results = []
    zero_lines = 0
    
    for output in outputs:
        try:
            parsed = fsm.ParseText(output)
            results.extend(parsed)
            
            # 检查: 是否有行的所有Value都是空的
            for row in parsed:
                if all(v == "" or v is None for v in row):
                    zero_lines += 1
                    
        except:
            continue
    
    # 计算覆盖率
    # 理想情况: 每个Value都原值都能被捕获
    coverage = _estimate_meaningful_extraction(
        template,
        raw_output,
        results
    )
    
    return ParseQualityMetrics(
        successful_parses=len(results),
        failed_parses=len(outputs) - len([p for p in results if p]),
        parse_success_rate=... ,
        avg_values_extracted=sum(len(r) for r in results) / len(results) if results else 0,
        zero_value_rate=zero_lines / len(results) if results else 0,
        value_consistency=_calculate_per_value_fill_rate(values_defined, results),
        estimated_coverage=coverage
    )
```

**优势:**
- ✅ 不再接受"语法对但没数据"的虚假成功
- ✅ 可以检测"模板太宽泛（捕获噪音）"或"太严格（捕获不到）"
- ✅ 更可靠的成功判定

---

### 改进 6️⃣: **跨迭代约束与历史记忆**

**方案:**

```python
def _build_generation_prompt_with_constraints(
    raw_output: str,
    command_name: str,
    platform: str,
    strategy: GenerationStrategy,
    failed_attempts: list[tuple[str, ErrorAnalysis]],
    ntc_references: list[str]
) -> str:
    """
    构建Prompt时加入约束条件，避免重复错误
    """
    
    base_prompt = load_skill_prompt("textfsm-generator", "generation")
    prompt = f"{base_prompt}\n"
    
    # 1. NTC参考
    if ntc_references:
        prompt += "\n## Reference Templates from NTC Library\n"
        for ref in ntc_references:
            prompt += f"```\n{ref[:300]}\n```\n"
    
    # 2. 历史失败约束
    if failed_attempts:
        prompt += "\n## DO NOT REPEAT These Mistakes\n\n"
        for i, (template, analysis) in enumerate(failed_attempts[-2:]):  # 最近2次
            prompt += f"**Attempt {i+1} Failure:**\n"
            prompt += f"- Error: {analysis.error_category}\n"
            prompt += f"- Issue: {analysis.specific_issue}\n"
            prompt += f"- Fix: {analysis.suggested_fix}\n\n"
    
    # 3. 策略指导
    if strategy == GenerationStrategy.SIMPLIFICATION:
        prompt += "\n## SIMPLIFICATION STRATEGY\n"
        prompt += "Focus on core fields only. Skip optional columns."
        prompt += "Prefer simple regex patterns over complex ones.\n"
    elif strategy == GenerationStrategy.TARGETED_FIX:
        prompt += "\n## TARGETED FIX STRATEGY\n"
        prompt += "Refine the existing template. Change only the problematic parts.\n"
    
    # 4. 输出格式约束
    prompt += "\n## Output Requirements\n"
    prompt += "- Minimum 3 Values (otherwise template is too simple)\n"
    prompt += "- Maximum 15 Values (otherwise template is too complex)\n"
    prompt += "- Each Value must match actual output patterns\n"
    
    return prompt
```

**优势:**
- ✅ LLM能看到"不要犯前面的错误"的明确指导
- ✅ 减少无效重复
- ✅ 实现有方向的迭代改进

---

### 改进 7️⃣: **降级策略与部分成功处理**

**方案:**

```python
def should_continue_iterating(state: TextfsmState) -> str:
    """
    更智能的迭代决策
    """
    quality = state.template_quality
    
    # 情况1: 好模板 → 完成
    if quality.overall_score >= 85:
        return "end"
    
    # 情况2: 部分成功模板 → 微调
    if quality.overall_score >= 70:
        if state.iteration < 2:  # 只做一次微调
            return "targeted_fix"
        else:
            # 已微调过，还是部分成功 → 接受它
            return "end_with_partial"
    
    # 情况3: 低质量 → 继续重试
    if state.iteration < state.max_iterations:
        return "retry_with_simplification"
    
    # 情况4: 已达上限 → 返回最好的迭代结果
    return "end_with_best_attempt"

async def apply_fallback_strategy(
    state: TextfsmState
) -> TextfsmState:
    """
    如果全部失败，应用降级策略
    """
    
    # 从所有尝试中找最好的那个
    best_template = max(
        state.failed_attempts,
        key=lambda x: x[1].overall_score if hasattr(x[1], 'overall_score') else 0
    )
    
    # 甚至那个"最好的"也只有40%成功
    # → 简化它，让它变成"70%但可靠"的版本
    
    simplified = await _simplify_template(
        best_template[0],
        state.raw_output,
        target_coverage=0.7  # 降低目标到70%覆盖率
    )
    
    state.template = simplified
    state.status = "success_with_fallback"
    
    return state
```

**优势:**
- ✅ 永远不返回空模板或完全失败结果
- ✅ "70%可用的模板"比"完美但不存在的模板"更有价值  
- ✅ 系统的鲁棒性提高

---

## 4. 实现优先级与ROI分析

| 改进 | 难度 | 预期收益 | 优先级 | 依赖关系 |
|------|------|---------|--------|---------|
| 1️⃣ 结构化错误分析 | ⭐⭐ | +10-15% | 🔴 高 | 无 |
| 2️⃣ 多维度评分 | ⭐⭐⭐ | +5-10% | 🔴 高 | 1️⃣ |
| 3️⃣ 动态策略选择 | ⭐⭐⭐⭐ | +10-20% | 🟡 中 | 1️⃣ 2️⃣ |
| 4️⃣ 智能NTC选择 | ⭐⭐ | +5-8% | 🟢 低 | 无 |
| 5️⃣ 语义验证 | ⭐⭐⭐ | +5-10% | 🟡 中 | 无 |
| 6️⃣ 历史记忆 | ⭐⭐ | +5-10% | 🟡 中 | 1️⃣ |
| 7️⃣ 降级策略 | ⭐⭐⭐ | +8-12% | 🟢 低 | 2️⃣ |

**综合预期:**
- **当前:** 70-85% (with NTC integration)
- **+阶段1** (1️⃣ 2️⃣): → 80-92%
- **+阶段2** (3️⃣ 5️⃣ 6️⃣): → 85-95%
- **+阶段3** (4️⃣ 7️⃣): → 88-96%

---

## 5. 建议迭代计划

### Phase 1: 基础改进 (1-2周)
1. ✅ 添加 ErrorAnalysis dataclass
2. ✅ 改进 analyze_node，返回结构化反馈
3. ✅ 改进 test_node，添加 TemplateQuality评分
4. ✅ 修改 generate_node，接收并使用历史反馈

### Phase 2: 智能决策 (2-3周)
1. ✅ 实现 GenerationStrategy 枚举和选择逻辑
2. ✅ 改进 _build_generation_prompt，支持约束
3. ✅ 实现 _validate_template_semantically
4. ✅ 测试各种场景

### Phase 3: 高级特性 (后续)
1. ⬜ 智能NTC选择  
2. ⬜ 降级策略
3. ⬜ 模板缓存与学习

---

## 6. 关键指标与验证

**测试场景（现有+新增）:**

| 场景 | 当前 | 改进后 | 验证方式 |
|------|------|--------|---------|
| 简单命令(show ver) | 95% | 98% | E2E test |
| 中等复杂(show bgp sum) | 70-80% | 85-92% | E2E test |
| 复杂命令(show route sum detail) | 40-50% | 75-85% | E2E test |
| 非标准输出 | 20-30% | 50-70% | E2E test |

---

## 7. 结论

**当前NTC集成给出了+30-45%的基础改进。**

**但要达到>90%的稳定成功率，架构层面需要：**

1. ✅ **智能反馈循环** - 结构化错误分析，而非模糊字符串
2. ✅ **自适应策略** - 根据失败模式动态调整生成方式
3. ✅ **质量梯度** - 多维度评分，而非二元判断
4. ✅ **记忆机制** - 跨迭代约束，避免重复失败
5. ✅ **鲁棒性设计** - 降级策略确保最差情况也可用

**不实现这些架构改进，即使进一步调优NTC或SKILL.md，收获也有限。**

---

**下一步:** 确认是否按照Phase 1 → Phase 2 → Phase 3的顺序实施改进。

