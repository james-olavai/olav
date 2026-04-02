---
name: olav-main
description: "Main OLAV Agent — Network Operations Assistant"
system_prompt_file: prompts/system.md
---

## Overview

The `olav` agent is a no-tool information agent. It answers questions about the platform,
explains capabilities, and helps route users to the right specialist agent.
It does NOT have database or CLI tools — use `quick`, `ops`, `config`, or `audit` for those.

Routes: `help`, `what can you do`, `status`, `health check`, `workspace`
