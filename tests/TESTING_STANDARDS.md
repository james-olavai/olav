# OLAV 测试标准

## 快速开始

```bash
# 运行所有单元测试
pytest tests/unit/ -v

# 运行单个测试文件
pytest tests/unit/test_format_and_export.py -v

# 运行特定测试
pytest tests/unit/test_format_and_export.py::TestCSVExport::test_heterogeneous_dicts_all_fields_present -v

# 带覆盖率
pytest tests/unit/ --cov=src/olav --cov-report=html
```

## 测试分类

| 标记 | 用途 | 依赖 | 示例命令 |
|------|------|------|----------|
| `@pytest.mark.unit` | 单元测试 | 无外部依赖 | `pytest -m unit` |
| `@pytest.mark.e2e` | 端到端测试 | 真实设备 | `pytest -m e2e` |
| `@pytest.mark.llm` | LLM测试 | API Key | `pytest -m llm` |
| `@pytest.mark.network` | 网络测试 | 设备连接 | `pytest -m network` |
| `@pytest.mark.slow` | 慢测试 | - | `pytest -m "not slow"` |

## 目录结构

```
tests/
├── conftest.py              # 共享fixtures
├── __init__.py
├── unit/                    # 单元测试 (无外部依赖)
│   ├── test_format_and_export.py
│   ├── test_sync_tools.py
│   └── test_inspection_skill.py
├── e2e/                     # 端到端测试 (真实设备)
│   └── test_cli.py
└── cli/                     # CLI测试 (subprocess)
    └── test_commands.py
```

## 测试编写规范

### 1. 命名约定

```python
# 文件名: test_<module>.py
# 类名: Test<Feature>
# 方法名: test_<scenario>_<expected_result>

class TestCSVExport:
    def test_heterogeneous_dicts_all_fields_present(self):
        ...

    def test_empty_list_returns_empty_file(self):
        ...
```

### 2. 边界条件必测

每个工具/函数必须测试：

```python
class TestRequired:
    def test_normal_case(self):          # 正常输入
    def test_empty_input(self):          # 空输入
    def test_single_item(self):          # 单项输入
    def test_heterogeneous_data(self):   # 异构数据
    def test_unicode(self):              # Unicode字符
    def test_special_characters(self):   # 特殊字符
    def test_security_boundary(self):    # 安全边界
```

### 3. 使用 tmp_path fixture

```python
def test_file_export(self, tmp_path: Path):
    # tmp_path 是 pytest 内置fixture，每个测试独立临时目录
    result = export_to_file(tmp_path / "output.csv")
    assert result.exists()
```

### 4. 异常测试

```python
def test_invalid_input_raises(self):
    with pytest.raises(ValueError, match="Invalid filename"):
        format_and_export(data=[], filename="../../../etc/passwd")
```

### 5. 跳过有依赖的测试

```python
@pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="No LLM_API_KEY")
def test_with_llm(self):
    ...
```

## 常见Bug类型与测试策略

### Bug: CSV fieldnames 不完整

**根因**: 只用第一个dict的keys作为fieldnames

**测试策略**:
```python
def test_heterogeneous_dicts(self):
    data = [
        {"a": 1},
        {"a": 2, "b": 3},  # 多字段
        {"a": 4, "c": 5},  # 又不同
    ]
    result = export_csv(data)
    assert all columns present in result
```

### Bug: 类型错误 (StructuredTool not callable)

**根因**: `@tool` 返回 `StructuredTool` 对象，不能直接调用

**测试策略**:
```python
def test_tool_invocation(self):
    from my_tool import my_tool
    # 正确: 使用 .invoke()
    result = my_tool.invoke({"param": "value"})
    assert result is not None
```

### Bug: 资源冲突 (DuckDB连接)

**根因**: 多个连接同时访问同一数据库文件

**测试策略**:
```python
def test_concurrent_access(self):
    import threading
    errors = []
    def query():
        try:
            execute_query("SELECT 1")
        except Exception as e:
            errors.append(e)
    
    threads = [threading.Thread(target=query) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    assert len(errors) == 0
```

## CI/CD 集成

```yaml
# .github/workflows/test.yml
- name: Run tests
  run: |
    pytest tests/unit/ -v --tb=short
    pytest tests/e2e/ -v --tb=short -m "not slow"
```

## 测试覆盖目标

| 模块类型 | 目标覆盖率 |
|----------|------------|
| 核心工具 | 90%+ |
| 数据导出 | 85%+ |
| Agent逻辑 | 70%+ |
| CLI命令 | 60%+ |

## 禁止的做法

```python
# ❌ 禁止: Mock核心业务逻辑
@patch('olav.tools.database.execute_sql')
def test_query(mock_sql):
    mock_sql.return_value = [{"fake": "data"}]

# ✅ 正确: 使用真实数据库(tmp_path)
def test_query(tmp_path):
    db = create_test_db(tmp_path)
    result = execute_sql("SELECT * FROM devices", db=db)
```

```python
# ❌ 禁止: 跳过失败测试
@pytest.mark.skip(reason="TODO: fix later")

# ✅ 正确: 修复或标记为已知问题
@pytest.mark.xfail(reason="Known issue with X, tracked in #123")
```

## 参考资料

- [pytest 官方文档](https://docs.pytest.org/)
- [pytest 最佳实践](https://testdriven.io/blog/testing-python/)

---

**最后更新**: 2026-02-23
**版本**: v1.0
