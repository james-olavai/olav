# OLAV - Network Operations AI Assistant

**Version**: v0.9.8

---

## 🎯 项目概述

OLAV (Open Logic Agent for Network Visibility and Analysis) is an intelligent network operations assistant built with DeepAgents framework.

### 核心特性

- **自然语言查询** - 用自然语言提问，OLAV 自动路由到合适的专家
- **精确缓存匹配** - 基于精确字符串匹配的快速响应
- **统一网络专家** - L2-L7 全栈网络诊断（BGP/OSPF/STP/VLAN/Security）
- **统一数据库** - DuckDB 跨数据库 JOINs 查询
- **ReAct 编排模式** - 自我修复、计划执行
- **命令历史记录** - 自动记录和补全常用命令

---

## 📊 v0.9.8 架构

### K.I.S.S. 原则架构 (Keep It Simple, Stupid)

**核心设计**:
- ✅ **精确匹配缓存** - 无语义搜索，无置信度分层
- ✅ **统一网络专家** - 单一 `network-expert` (包含 L2/L3/Security)
- ✅ **简化实现** - 删除复杂的向量搜索和多级 Agent

**缓存策略**:
- **精确字符串匹配** - `query_text` 完全匹配，缓存命中为 true/false
- **统一缓存表** - `commands.main.semantic_cache`（不使用 embedding 列）
- **无置信度层级** - 不使用 0.90/0.95/0.97 等复杂分层

**专家架构**:
- **network-expert** - 统一的 L2-L7 网络诊断专家
  - L2: VLAN, STP, LACP
  - L3: BGP, OSPF, Static Routing  
  - Security: ACL, VPN, NAT, Firewall

**查询逻辑**:
1. 精确字符串匹配缓存（`query == cached_query`）
2. 如果命中：直接返回缓存结果（< 2s）
3. 如果未命中：调用 network-expert（3-10s）

**适用场景**:
- IP 地址/设备名查询：精确匹配，不接受近似
- 路由表/BGP 邻居：精确匹配设备名
- 安全策略/ACL：精确匹配规则名

---

## 📁 项目文档

### 🚀 开始开发
- **[开发者指南](docs/01_developer_guide.md)** ⭐ **新人必读** - 5分钟快速开始
- **[开发路线图](docs/00_roadmap.md)** - v0.9.8 开发任务清单
- **[代码规范](docs/03_development_spec.md)** - 质量要求和开发规范

### 📖 参考文档
- **[架构审计报告](docs/100_audit_report.md)** - 架构决策和历史问题
- **[代码清理清单](docs/98_cleanup_checklist.md)** - Phase 1 清理指南

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

**当前版本**: v0.9.8  
**最后更新**: 2026-01-31  
**架构决策**: 精确匹配缓存 + 统一网络专家  
**开发状态**: 稳定版本

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
