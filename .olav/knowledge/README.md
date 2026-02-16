# OLAV Knowledge Base

**Location**: `.olav/knowledge/`  
**Storage**: Flat structure (all files in single directory)  
**Indexing**: Automatic via `olav admin kb-index` or `olav admin kb-reload`

---

## 📂 文件组织

所有知识库文件直接存储在本目录中，**无子目录分类**：

```
.olav/knowledge/
├── bgp_troubleshooting.md          # 故障排査指南
├── ospf_neighbor_down_case.md      # 历史案例
├── cisco_bgp_commands.md           # 厂商命令参考
├── vxlan_best_practices.md         # 最佳实践
├── 2026-02-15_r1_cpu_spike.md      # 事故记录
└── README.md                        # 本文件
```

**为什么不分目录？**
- ✅ 搜索时不需要指定路径
- ✅ 文件名即可标识内容
- ✅ 遵循 KISS 原则
- ✅ 避免过度分类的认知负担

---

## 📝 文档添加指南

### 步骤 1: 创建 Markdown 文件

```bash
# 创建新文档
cat > .olav/knowledge/your_topic.md << 'EOF'
# 文档标题

## 概述
文档内容...

## 详细说明
...
EOF
```

### 步骤 2: 重新索引知识库

```bash
# 增量索引（推荐）
olav admin kb-reload

# 完全重建
olav admin kb-index --rebuild
```

### 步骤 3: 测试搜索

```bash
# 测试搜索结果
olav admin kb-search "BGP troubleshooting"
```

---

## 📋 文档类型参考

### 故障排查指南

```markdown
# BGP Neighbor Down 故障排查

## 症状
- Neighbor not reachable
- Stuck in Connect state

## 排查步骤
1. Check connectivity: `ping <neighbor>`
2. Verify configuration: `show bgp neighbors`
```

### 历史案例

```markdown
# 2026-02-15 R1 CPU Spike Incident

## 事件
- **时间**: 2026-02-15 14:30 UTC
- **原因**: BGP route flapping

## 解决方案
Updated prefix-list configuration
```

### 最佳实践

```markdown
# VXLAN EVPN Design Best Practices

## 拓扑设计
- Spine-Leaf 架构
- 每 Leaf 连 2+ Spine
```

---

## 🔍 搜索工作流

用户查询"BGP 邻接关系失败" →

1. 系统向量搜索：`search_knowledge("BGP neighbor down")`
2. 返回排名前 3 文档（相似度 > 0.7）
3. Agent 结合数据库信息进行诊断

---

## ⚙️ 管理命令

```bash
# 索引知识库（首次）
olav admin kb-index

# 增量更新（推荐）
olav admin kb-reload

# 查看索引状态
olav admin kb-status

# 搜索测试
olav admin kb-search "query"
```

---

## 🎯 成功标准

- [x] 扁平目录结构
- [ ] 文档 > 10 篇
- [ ] 搜索延迟 P95 < 300ms
- [ ] 搜索准确度 recall@3 > 85%

**Last Updated**: 2026-02-17

# 强制重新索引（rebuild）
olav admin kb-index rebuild

# 增量更新（下次添加新文件后）
olav admin kb-reload
```

✨ **说明**:
- `kb-index`: 初始化或增量索引（跳过已索引的文件）
- `kb-reload`: 完全重建索引（开销较大，建议月度执行）

### 3. 查询知识库

```bash
# 通过 Expert Agent 
olav ask "BGP neighbor down 怎么办？"
# 预期：Agent 会自动调用 search_knowledge() 查找相关文档

# 通过 CLI 直接搜索
olav admin kb-search "OSPF 配置"
```

### 4. 查看索引状态

```bash
olav admin kb-status

# 输出示例
📚 Knowledge Base Status
  Status: indexed
  Files:   5
  Chunks:  127
  Updated: 2026-02-16 21:45:30
```

## 🔍 搜索工作流

1. **Agent 接收用户查询**  
   ```
   User: "BGP neighbor 经常 flapping，怎么办？"
   ```

2. **Agent 自动调用工具**
   ```
   search_knowledge("BGP neighbor flapping troubleshooting", limit=3)
   ```

3. **返回相关文档** (向量相似度搜索)
   ```
   ✅ [1] bgp_troubleshooting.md (相似度: 92%)
      When a BGP neighbor continuously transitions between Up and Down...
   ✅ [2] bgp_failure_cases.md (相似度: 87%)
      Historical: Router R1 BGP flapping due to...
   ✅ [3] bgp_timers.md (相似度: 78%)
      BGP Holddown timer...
   ```

4. **如果无相关知识库结果**  
   ```
   web_search("Cisco BGP neighbor flapping 2026")
   ```

## 💾 数据存储

- **位置**: `.olav/databases/main.duckdb`
- **表名**: `knowledge_chunks`
- **存储内容**:
  - 文档块（chunk）内容
  - 向量嵌入（1536维）
  - 源文件名
  - 索引时间

## 📊 性能指标

| 指标 | 目标 | 说明 |
|------|------|------|
| 搜索延迟 P95 | < 300ms | 从查询到返回结果 |
| 准确度 (recall@3) | > 85% | top 3 包含相关文档 |
| 索引成本 | < $1/月 | OpenAI embeddings 成本 |
| 存储体积 | < 50MB | DuckDB 增长量 |

## 🎯 最佳实践

### ✅ 好的例子

**文件名** (清晰具体)
- `bgp_authentication_setup.md` ✨
- `ospf_timers_optimization.md` ✨
- `vxlan_evpn_design_2026.md` ✨

**文档内容** (结构化)
```markdown
# 标题（主题）

## 症状（What to look for）
- 症状 1
- 症状 2

## 原因（Root causes）
- 原因 1
- 原因 2

## 排查步骤（Troubleshooting steps）
1. 第一步
2. 第二步
3. ...

## 参考资源（References）
- 链接
- 文档
```

### ❌ 避免的做法

- ❌ 创建子目录: `.olav/knowledge/guides/`, `.olav/knowledge/cases/`
- ❌ 过长文件名: `this_is_a_very_long_and_confusing_filename_that_nobody_understands.md`
- ❌ 重复内容: 多个同类型文档应合并
- ❌ 过期信息: 应标注日期或删除

## 🔄 定期维护

### 每周
- [ ] 确认新添加的文档无拼写错误
- [ ] 验证 Markdown 格式正确

### 每月
```bash
# 清理过期文档
ls -lh .olav/knowledge/*.md | grep "2024\|2023"  # 列出旧文档

# 重新索引
olav admin kb-reload
```

### 每季度
```bash
# 审查所有文档
ls .olav/knowledge/*.md | wc -l  # 统计文档数

# 备份
olav admin backup
```

## ❓ FAQ

**Q: 我意外删除了一个文档，能恢复吗？**  
A: 可以通过 Git history 恢复（`git checkout .olav/knowledge/`），或从备份恢复（`olav admin restore <backup>`）。

**Q: 搜索结果精度太低，怎么办？**  
A: 索引向量在第一次创建后是固定的。请：
1. 改进文档内容（使用更精准的术语）
2. 重新索引：`olav admin kb-reload`
3. 尝试更具体的搜索词

**Q: 可以使用不同的嵌入模型吗？**  
A: 当前使用 OpenAI's `text-embedding-3-small` (1536-dim)。修改需要编辑 `config/settings.py` 并重新索引。

**Q: 索引过程花了很久，正常吗？**  
A: 正常。速度取决于：
- 文档数量和大小
- 网络延迟（OpenAI API）
- 计算资源
- 首次索引通常较慢，增量更新较快

**Q: 能离线使用吗？**  
A: 索引和搜索需要通过 OpenAI API，在线使用。向量计算无法离线进行。

## 📞 辅助命令

```bash
# 快速检查
olav admin kb-status

# 搜索测试
olav admin kb-search "BGP configuration"

# 查看知识库目录
ls -lh .olav/knowledge/

# 统计文档
find .olav/knowledge -name "*.md" | wc -l

# 查看最近修改
ls -lt .olav/knowledge/*.md | head -5
```

## 📖 相关文档

- [Knowledge Base Design](../../dev_docs/KNOWLEDGE_BASE_DESIGN.md) - 技术设计文档
- [Admin CLI](../CLI_REFERENCE.md) - CLI 命令参考
- [OLAV 主文档](../../README.md) - 项目主文档

---

**Version**: v1.0.0  
**Last Updated**: 2026-02-16  
**Status**: ✅ Ready for Use  
**Maintenance**: Monthly  
**Owner**: Admin/Knowledge Team
