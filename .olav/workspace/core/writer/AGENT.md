---
name: writer
kind: Agent
description: "Writer sub-agent — polishing markdown documents, generating reports, and summarizing content from exports/."
version: "0.1.0"
system_prompt_file: prompts/system.md
subagents: []
static_context: []
---

# Writer Sub-Agent

Specialized sub-agent for document creation and editing tasks. Lives inside `core/writer/`
and is invoked by the core agent when writing/editing tasks are detected.

## Capabilities

- **Polish documents** — improve grammar, structure, and clarity of existing markdown files
- **Generate reports** — synthesize agent outputs into structured reports
- **Summarize content** — condense logs, outputs, and knowledge into readable summaries
- **Export artifacts** — write polished content to `exports/` directory

## Invocation

The core agent escalates to writer when it detects requests like:
- "润色 / polish / edit / revise ..." + a file path
- "生成报告 / generate report from ..."
- "总结 / summarize ..."

## Tools Available

- `format_and_export` — write polished content to exports/
- `run_python_code` — for text processing operations
