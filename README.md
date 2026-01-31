# OLAV - Network Operations AI Assistant

**Version**: v0.9.7 (Simplified Fast Path Architecture)

---

## 🎯 项目概述

OLAV (Open Logic Agent for Network Visibility and Analysis) is an intelligent network operations assistant built with DeepAgents framework.

### 核心特性

- **自然语言查询** - 用自然语言提问，OLAV 自动路由到合适的专家
- **命令历史记录** - 自动记录和补全常用命令
- **快速路径（Fast Path）** - 缓存常用查询，实现秒级响应
- **分层专家路由** - 数据库、CLI、安全、路由、BGP 等专家
- **统一数据库** - DuckDB 跨数据库 JOINs 查询
- **ReAct 编排模式** - 自我修复、计划执行

---

## 📊 当前架构

### 简化的 Fast Path 架构

**核心原则：** K.I.S.S. (Keep It Simple, Stupid)

**缓存策略：**
- **一层 SQL 缓存** - 只用 `commands.main.semantic_cache`
- **每个 Agent 独立缓存** - 每个 agent 一个 `.duckdb` 文件
- **精确匹配** - 缓存命中就是简单的 `true/false` 判断
- **无复杂置信度** - 不使用多级置信度分层（0.90/0.95/0.97）

**查询逻辑：**
1. 检查 Agent 自己的缓存
2. 精确字符串匹配（`query == cached_query`）
3. 如果命中：返回缓存的执行计划
4. 如果未命中：Agent 正常处理并学习

**网络运维场景：**
- IP 地址查询：**精确匹配**，不接受模糊匹配
- 路由表查询：精确匹配设备名
- BGP 邻居查询：精确匹配设备名

---

## 📁 项目文档

- **[架构设计](docs/architecture_simplified_final.md)** - 简化架构的最终设计文档
- **[路线图](docs/00_roadmap.md)** - 项目路线图
- **[开发规范](docs/03_development_spec.md)** - 开发规范和代码质量要求
- **[项目进度](docs/99_project_progress.md)** - 当前开发进度追踪

---

## 🚀 快速开始

### 环境要求

```bash
# 安装依赖
pip install duckdb langchain openai
pip install -e .[dev]
```

### 运行 OLAV

```bash
# 交互模式
uv run olav

# 单次查询
uv run olav query "显示 R1 的接口状态"

# 命令行
uv run olav --help
```

---

## 📋 开发分支

- **`main`** - 稳定版本
- **`feature/fast-path-0.9xx`** - Fast Path 开发分支（当前）

---

## 🔍 常见问题

**Q: 如何清空命令历史？**
```bash
uv run python3 -c "from olav.cli.session import clear_cli_history; clear_cli_history()"
```

**Q: 如何测试 Fast Path 性能？**
```bash
uv run pytest tests/00_e2e_acceptance_test.py::TestFastPath -v
```

**Q: 如何添加新的专家？**
```bash
# 1. 在 `config/routing_rules.yaml` 中添加专家定义
# 2. 在 `skills/` 目录下创建对应的 SKILL.md
# 3. 专家会自动被路由器识别
```

---

## 📞 项目状态

**当前版本**: v0.9.7-dev
**最后更新**: 2026-01-31
**开发状态**: Phase 1.0 (Per-Agent Caching) 进行中

---

## 📜 许可证

MIT License - 详见 LICENSE 文件

---

## 🤝 贡献指南

欢迎贡献！请先阅读 [开发规范](docs/03_development_spec.md) 了解代码风格和提交流程。

---

## 📧 维护者

- **AI 项目经理**: OpenClaw AI Assistant
- **核心开发**: DeepAgents + Fast Path 优化

---

**OLAV - 让网络运维更简单、更智能！** 🚀
