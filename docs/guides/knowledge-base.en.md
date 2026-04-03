# Knowledge Base

OLAV includes a built-in semantic search knowledge base — you can import your team's operations documentation, runbooks, incident response playbooks, and more into OLAV, then search them using natural language.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-21 | Knowledge base indexes documents and supports semantic search (vector + BM25 hybrid) | ✅ v0.10.0 |

---

## Use Cases

- "What is the standard procedure for BGP failover?"
- "Where are the disaster recovery steps?"
- "What was the solution used last time for this issue?"

No need to dig through Confluence, search the Wiki, or hunt through emails — just ask OLAV.

---

## Importing Documents

Supported formats: `.md` (Markdown), `.pdf`, `.txt`. Place files in the `.olav/knowledge/` directory, then index them:

```bash
olav --agent config "索引所有知识库文件"
```

Check indexing status:

```bash
olav --agent config "显示知识库状态"
```

---

## Searching the Knowledge Base

Ask questions directly in natural language:

```bash
olav "我们的 Runbook 里关于 BGP 故障切换是怎么说的？"
olav --agent config "在知识库中搜索 'DR 流程'"
```

OLAV returns the most relevant document snippets and generates a comprehensive answer using the LLM.

---

## How It Works

The knowledge base uses vector semantic search combined with BM25 keyword search (RRF fusion ranking). This approach understands semantic similarity while ensuring keyword matches are not missed:

```
Document → Chunking (~1024 chars) → Generate vector embeddings → Store in LanceDB
Query → Vector similarity search + BM25 keyword search → Fusion ranking → Return Top-N snippets → LLM synthesized answer
```

---

## Configuring Vector Embeddings

Configure the embedding model in `.olav/config/api.json`:

=== "API Mode (Recommended)"
    ```json
    "embedding": {
      "mode": "api",
      "api": {
        "model": "openai/text-embedding-3-small",
        "base_url": "https://openrouter.ai/api/v1"
      }
    }
    ```

=== "Local Mode (Offline / Air-Gapped Environments)"
    ```json
    "embedding": {
      "mode": "local"
    }
    ```
    Uses the BAAI/bge model. CPU-only, no network connection required. Suitable for security-isolated environments.

!!! note "Knowledge Base vs Agent Memory"
    The knowledge base stores documents you explicitly import. Agent memory (LanceDB) stores lessons learned automatically during OLAV operation (via `/trace-review`). Both support semantic search, but serve different purposes.
