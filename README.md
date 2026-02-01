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
## 🏆 最新改进 - Phase 1 & Phase 2 完成

### 硬编码消除 (52% 改进 ✅)
- **原始问题**: 23项硬编码违规
- **Phase 1 完成**: 48% 改进 (23→12)
- **Phase 2 完成**: 8% 改进 (12→11)
- **总成果**: 52% 改进 + 5层配置系统

**改进成果**:
- ✅ 5层配置优先级系统 (.env > .olav/settings.json > SKILL.md > settings.py > 代码默认)
- ✅ 所有参数完全可配置 (Nornir组名、权重、阈值、路径)
- ✅ 100% 向后兼容 (零破坏性变更)
- ✅ 所有测试通过 (语法+功能+集成)

**详见**: 
- 📋 [Phase 1-2 完成总结](PHASE1_PHASE2_COMPLETION_SUMMARY.md) - 核心成就与验收数据
- 📊 [硬编码修复汇总](HARDCODE_FIXES_SUMMARY.md) - 23项问题详细分析
- 🗺️ [改进路线图](HARDCODE_IMPROVEMENTS_ROADMAP.md) - Phase 3-4 规划

---
## 📁 项目文档

### 🚀 开始开发
- **[完整开发指南](docs/00_development_guide.md)** ⭐ **新人必读** - 完整的开发者手册
  - 项目概述与快速开始
  - 架构设计详解
  - 开发规范与测试策略
  - 部署指南与常见问题
  
- **[文档索引](docs/README.md)** - 📚 所有文档导航

### � 历史文档
- **[归档目录](docs/_archive/)** - 历史设计文档、审计报告（核心内容已整合到开发指南）

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
