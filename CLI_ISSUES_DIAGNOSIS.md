# CLI 问题诊断与修复计划

## 问题 1: CommandHistory 模块加载失败

**症状**:
```
WARNING - CommandHistory module not available, history disabled
ERROR - Failed to load history: 'InMemoryHistory' object has no attribute 'load_history'
```

**根本原因**:
- `CommandHistory` 模块可能不存在或导入失败
- `FileHistory` 对象没有 `load_history()` 方法（prompt_toolkit API 不支持）

**修复方案**:
1. 检查 CommandHistory 导入
2. 移除无效的 `load_history()` 调用
3. 使用正确的 prompt_toolkit API

---

## 问题 2: 异步事件循环冲突

**症状**:
```
RuntimeWarning: coroutine 'Application.run_async' was never awaited
WARNING - Learning callback error: asyncio.run() cannot be called from a running event loop
```

**根本原因**:
- 在已运行的事件循环中调用 `asyncio.run()`
- CLI 主程序使用 typer（基于 click），在异步上下文中不正确地使用 asyncio

**修复方案**:
1. 使用 `asyncio.create_task()` 替代 `asyncio.run()`
2. 或使用 `nest_asyncio` 库处理嵌套事件循环
3. 重构异步流程

---

## 问题 3: Markdown 输出渲染

**症状**:
- 结果没有通过 markdown 格式输出
- 缺少 markdown 渲染支持

**修复方案**:
1. 在 `StreamingDisplay` 中添加 markdown 渲染
2. 使用 rich 的 `Markdown` 类
3. 改进输出格式化

---

## 问题 4: 数据库不完整

**症状**:
```
[{'device': 'R3', ...}]  # 只有 1 条记录
```

**修复方案**:
1. 检查数据库中的设备数量
2. 如果不完整，执行 snapshot 采集
3. 提供快速修复命令

---

## 问题 5: CLI 交互功能

**症状**:
- 历史记录功能消失
- Tab 补全功能消失

**修复方案**:
1. 修复 session.py 中的历史记录加载
2. 恢复 tab 补全功能
3. 测试交互功能

