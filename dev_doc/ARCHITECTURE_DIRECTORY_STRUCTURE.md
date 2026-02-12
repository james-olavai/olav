# OLAV 目录结构 - 清晰的架构划分

**日期**: 2026-02-12  
**目的**: 澄清每个目录的用途，防止混淆

---

## 🏗️ 顶级目录划分

### 核心原则

```
【程序 vs 数据】清晰分离

.olav/
├─ 【代码】skills/shared/tools/  ← Skill代码和工具
├─ 【代码】skills/*/             ← Skill定义
├─ 【代码】scripts/              ← 初始化、迁移等脚本
├─ 【代码】commands/             ← CLI命令定义
│
├─ 【配置】config/               ← 应用配置文件
├─ 【配置】settings.json         ← 当前配置
├─ 【配置】OLAV.md               ← SubAgent注册表
│
└─ 【运行时数据】
   ├─ db/       ← 数据库文件（main.duckdb等）
   ├─ cache/    ← 缓存数据
   ├─ data/     ← 导入的原始数据
   ├─ knowledge/ ← 知识库
   ├─ reports/  ← 生成的报告
   ├─ scratch/  ← 临时文件
   └─ tasks/    ← 任务执行记录
```

---

## 📂 详细分析

### ✅ 应该在 `.olav/skills/shared/tools/` 下的

**定义**: 可复用的**代码和实现**，被多个Skill使用

```
.olav/skills/shared/tools/
├─ data_export.py          ← wrapper:导出数据
├─ network_executor.py     ← wrapper:网络执行
├─ report_formatter.py     ← wrapper:报告生成
├─ sync_tools.py           ← wrapper:数据同步
├─ query_database.py       ← wrapper:查询DB
└─ discover_data.py        ← wrapper:数据发现

【特点】
- 代码文件（.py）
- 可复用的函数和类
- 不会改变，除非功能升级
```

**原则**: 
- ✅ Python代码文件
- ✅ 函数和类定义
- ✅ 可在多个Skill中导入使用
- ❌ 运行时生成的数据
- ❌ 配置文件

---

### ❌ 不应该在 `skills/shared/tools/` 下的

#### 1️⃣ **数据库文件** (.olav/db/)

```
.olav/db/
├─ main.duckdb           ← 设备数据
├─ olav.duckdb           ← OLAV系统数据
└─ *.db                  ← 其他数据库

【为什么在这里】
- 运行时生成的持久化数据
- 所有Skill共享，但不是"工具代码"
- 会不断更新（INSERT/UPDATE/DELETE）
- 大文件（MB级别），不是代码

【不应该在】.olav/skills/shared/tools/
- tools/应该只有代码
- 如果放过去，tools目录会混乱
- 难以管理版本控制（数据库很难git管理）
```

**位置决策**:
```
✅ 保持在 .olav/db/
❌ 不要移到 .olav/skills/shared/tools/
```

---

#### 2️⃣ **配置文件** (.olav/config/)

```
.olav/config/
├─ settings.json         ← 系统设置
├─ paths.py              ← 路径配置
├─ logging.py            ← 日志配置
└─ ...

【为什么在这里】
- 应用启动时的配置信息
- 所有Skill和模块都需要
- 会被修改（用户改设置）
- Plain data（JSON/YAML），不是代码

【不应该在】.olav/skills/shared/tools/
- tools/是代码容器
- config是全局系统配置
- 职责不同
```

**位置决策**:
```
✅ 保持在 .olav/config/
❌ 不要移到 .olav/skills/shared/tools/
```

---

#### 3️⃣ **缓存** (.olav/cache/)

```
.olav/cache/
├─ query_cache.db       ← 查询缓存
├─ embedding_cache/     ← 向量缓存
└─ ...

【为什么在这里】
- 运行时生成的优化数据
- 可以安全删除（缓存）
- 不是持久化业务数据
```

**位置决策**:
```
✅ 保持在 .olav/cache/
❌ 不要移到 .olav/skills/shared/tools/
```

---

#### 4️⃣ **知识库** (.olav/knowledge/)

```
.olav/knowledge/
├─ networks/
│   ├─ device_configs/
│   └─ topology/
└─ ...

【为什么在这里】
- 导入的、学习的网络知识
- 业务数据，不是工具代码
- 用于LLM上下文
```

**位置决策**:
```
✅ 保持在 .olav/knowledge/
❌ 不要移到 .olav/skills/shared/tools/
```

---

## 🎯 完整的合理架构

```
.olav/
│
├─【全局系统配置】 ← 应用启动需要
│  ├─ config/
│  │  └─ settings.json, paths.py, logging.py, ...
│  ├─ settings.json (当前设置)
│  └─ OLAV.md (SubAgent注册表)
│
├─【全局运行时数据】← 执行过程中生成
│  ├─ db/ (持久化数据库)
│  ├─ cache/ (可清除的缓存)
│  ├─ data/ (导入的原始数据)
│  ├─ knowledge/ (学习的知识)
│  ├─ reports/ (生成的报告)
│  └─ scratch/ (临时文件)
│
├─【可复用的代码】 ← Skill-Centric架构
│  └─ skills/
│     ├─ shared/
│     │  └─ tools/
│     │     ├─ data_export.py (wrapper)
│     │     ├─ network_executor.py (wrapper)
│     │     ├─ report_formatter.py (wrapper)
│     │     └─ ... (其他wrapper)
│     │
│     └─ {skill_name}/
│        ├─ SKILL.md (定义)
│        └─ tools/ (skill特定工具)
│
└─【其他代码工件】
   ├─ scripts/ (初始化、迁移脚本)
   ├─ commands/ (CLI命令定义)
   ├─ workflows/ (工作流定义)
   └─ templates/ (模板)
```

---

## 📊 三种类型对比

| 类型 | 位置 | 例子 | 特点 | 能git管理吗 |
|------|------|------|------|----------|
| **代码** | `.olav/skills/shared/tools/` | `data_export.py` | 文本、可复用、不改 | ✅ 是 |
| **配置** | `.olav/config/` | `settings.json` | 文本、全局、会改 | ✅ 是 |
| **数据** | `.olav/db/`, `.olav/cache/` | `.duckdb` 文件 | 二进制、运行时生成 | ❌ 否 |

---

## 🤔 答案总结

### Q: db和config应该放到skills/shared下吗？

**A: 不应该。理由：**

1. **职责分离**
   - `.olav/skills/shared/tools/` = 代码和工具
   - `.olav/config/` = 系统配置
   - `.olav/db/` = 运行时数据

2. **可维护性**
   - 代码通常要版本控制（git）
   - 数据库文件不应该在git中（太大且会变化）
   - 如果混在一起，会很混乱

3. **概念清晰**
   - Skill-Centric架构讲的是"组织代码和工具"
   - 不是"把所有东西都放到skills下"
   - Config和db是全局资源，不属于任何单个Skill

---

## 📋 正确的迁移清单

```
【应该做的】✅
□ src/olav/tools/ → .olav/skills/shared/tools/ (代码迁移)
□ src/olav/agents/ → 修改导入路径

【不应该做的】❌
□ 不要把.olav/config/移到skills/shared/
□ 不要把.olav/db/移到skills/shared/
□ 不要把.olav/cache/移到skills/shared/
□ 不要把.olav/knowledge/移到skills/shared/

【保持原样】✅
□ .olav/config/ - 项目级配置
□ .olav/db/ - 项目级数据库
□ .olav/cache/ - 项目级缓存
□ src/olav/lib/ - 应用核心库（if exists）
```

---

## 🎯 最终架构建议

如果问题是"怎样让架构更Skill-Centric"，答案是：

```
【NO】不要把db、config等都放到skills/shared/

【YES】应该这样：
- 把 src/olav/tools/ 的代码 → .olav/skills/shared/tools/
- 把 src/olav/agents/ 的导入改为用wrapper
- 保持 db、config等在全局位置
- 每个Skill可以访问全局db、config、cache

【结果】
✅ 代码清晰（工具集中在skills/shared/tools/）
✅ 数据清晰（db、cache在全局）
✅ 配置清晰（config在全局）
✅ Skill-Centric（每个Skill是独立单元，但共享工具和资源）
```

---

**版本**: v1.0.0  
**日期**: 2026-02-12  
**目的**: 指导正确的目录结构和迁移范围
