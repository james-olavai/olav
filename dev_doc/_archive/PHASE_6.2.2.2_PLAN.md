# Phase 6.2.2.2: Enhanced Dependency Visualization

**Status**: Planning  
**Phase**: 6.2.2.2  
**Timeline**: 1-2 days  
**Goal**: Improve dependency flow diagram for complex execution plans  

---

## 🎯 Objectives

### Primary
1. Better ASCII art flow diagrams for complex dependencies
2. Show which steps can run in parallel
3. Highlight potential optimization opportunities
4. Display dependency details (who consumes what output)

### Secondary
1. Support for more complex dependency patterns
2. Tree-like visualization for DAG structures
3. Optimization suggestions based on parallelization

---

## 📋 Implementation Plan

### Flow Diagram Enhancement

**Current Output** (Linear 3-step):
```
[1️⃣ QUERY] (20s)
    ↓
[2️⃣ NETBOX] (45s)
    ↓
[3️⃣ ANALYZER] (20s)

✅ 完成！
```

**Enhanced Output** (Same 3-step with parallelization info):
```
🔴 No parallelization opportunities found

[1️⃣ QUERY] (20s)
    ↓
[2️⃣ NETBOX] (45s) [depends on: network_devices_data]
    ↓
[3️⃣ ANALYZER] (20s) [depends on: network_devices_data, netbox_data]

✅ 完成！

关键路径: QUERY (20s) → NETBOX (45s) → ANALYZER (20s) = 1m 25s
```

### Parallelization Detection

**Algorithm**:
```python
def can_run_parallel(steps):
    # Step A and B can run in parallel if:
    # 1. A's dependencies don't include B's output
    # 2. B's dependencies don't include A's output
    # 3. Neither depends on the other
    
    parallel_groups = []
    for group in find_independent_steps(steps):
        if len(group) > 1:
            parallel_groups.append(group)
    return parallel_groups
```

**Example** (Hypothetical 4-step with parallelization):
```
[1️⃣ QUERY] (20s)
    ├─────────────────┐
    ↓                 ↓
[2️⃣ NETBOX] (45s)  [3️⃣ BGP] (30s)  [CAN RUN IN PARALLEL]
    └─────────────────┤
                     ↓
                [4️⃣ ANALYZER] (20s)

✅ 完成！

💡 并行机会: NETBOX 和 BGP 可以同时运行 (节省45s)
  - 无并行: 20 + 45 + 30 + 20 = 2m 55s
  - 有并行: 20 + max(45, 30) + 20 = 1m 25s
  - 时间节约: 1m 30s (51%)
```

---

## 🧪 Testing Strategy

### RED Tests
1. test_flow_diagram_linear_generation - Linear flow (current)
2. test_flow_diagram_branch_detection - Branching flow
3. test_parallelization_detection - Find parallel steps
4. test_parallelization_savings - Calculate time savings

### Integration
- Test with different dependency patterns
- Verify ASCII art formatting
- Check emoji placement

---

## 💾 Implementation Steps

1. **Create flow_diagram_builder.py** (~200 lines)
   - FlowDiagramBuilder class
   - generate_ascii_diagram() for ASCII art
   - detect_parallel_steps() for parallelization

2. **Modify time_estimator.py** (~30 lines)
   - get_parallelization_savings() method
   - calculate_parallel_execution_time() function

3. **Update plan_mode_handler()** (~50 lines)
   - Use FlowDiagramBuilder to generate diagrams
   - Show parallelization info in output
   - Include optimization suggestions

4. **Add RED tests** (~150 lines)
   - 4+ test methods
   - Verify ASCII art output
   - Check parallelization detection

---

## 📊 Expected Impact

| Metric | Before | After | Improvement |
|--------|--------|-------|------------|
| Visibility of parallelization | None | 🟢 Clear | Yes |
| Optimization suggestions | None | 💡 Provided | Yes |
| Diagram readability | Good | Better | +10% |
| Support for complex DAGs | Partial | Full | Yes |

---

## 🎓 Next Phases

**Phase 6.2.4 - Input Validation** (After 6.2.2.2)
- Validate user intent
- Check required config
- Warn about missing resources

**Phase 6.2.3 - User Confirmation** (After 6.2.4)
- Y/n/edit interaction
- Execute SubAgents
- Pass context between steps

---

**Phase**: 6.2.2.2 Planning  
**Status**: Ready for Implementation  
**Estimated Duration**: 1-2 days  
**Next Action**: Create flow_diagram_builder.py module
