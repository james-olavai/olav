# 知识库

OLAV 内置了语义搜索知识库——你可以把团队的运维文档、Runbook、故障处理手册等导入 OLAV，然后用自然语言搜索。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-21 | 知识库索引文档并支持语义搜索（向量 + BM25 混合） | ✅ v0.10.0 |

---

## 适用场景

- "BGP 故障切换的标准流程是什么？"
- "灾难恢复的步骤在哪里？"
- "上次处理这个问题的方案是什么？"

不用翻 Confluence、找 Wiki、搜邮件——直接问 OLAV。

---

## 导入文档

支持 `.md`（Markdown）、`.pdf`、`.txt` 格式。将文件放入 `.olav/knowledge/` 目录，然后索引：

```bash
olav --agent config "索引所有知识库文件"
```

查看索引状态：

```bash
olav --agent config "显示知识库状态"
```

---

## 搜索知识库

直接用自然语言提问：

```bash
olav "我们的 Runbook 里关于 BGP 故障切换是怎么说的？"
olav --agent config "在知识库中搜索 'DR 流程'"
```

OLAV 会返回最相关的文档片段，并结合 LLM 生成综合回答。

---

## 工作原理

知识库使用向量语义搜索，结合 BM25 关键词搜索（RRF 融合排序），既能理解语义相似度，又不会遗漏关键词匹配：

```
文档 → 分块（~1024 字符）→ 生成向量嵌入 → 存入 LanceDB
查询 → 向量相似度搜索 + BM25 关键词搜索 → 融合排序 → 返回 Top-N 片段 → LLM 综合回答
```

---

## 配置向量嵌入

在 `.olav/config/api.json` 中配置嵌入模型：

=== "API 模式（推荐）"
    ```json
    "embedding": {
      "mode": "api",
      "api": {
        "model": "openai/text-embedding-3-small",
        "base_url": "https://openrouter.ai/api/v1"
      }
    }
    ```

=== "本地模式（离线/气隙环境）"
    ```json
    "embedding": {
      "mode": "local"
    }
    ```
    使用 BAAI/bge 模型，仅需 CPU，无需网络连接。适合安全隔离环境。

!!! note "知识库 vs Agent 记忆"
    知识库存储你主动导入的文档。Agent 记忆（LanceDB）存储 OLAV 运行过程中自动学到的经验教训（通过 `/trace-review`）。两者都支持语义搜索，但用途不同。
