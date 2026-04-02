---
name: ops-lab-standalone
description: >
  ContainerLab digital twin validation (standalone agent). Deploy SR Linux containers
  from snapshot DB, push production-equivalent config, verify protocol convergence,
  tear down labs. Direct invocation without ops orchestrator overhead.
tools:
  - execute_sql
  - run_python_simulation
  - deploy_lab
  - call_api
  - exec_on_node
  - create_srl_links
  - fix_srl_topology
---
