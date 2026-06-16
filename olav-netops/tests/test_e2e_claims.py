"""NetOps E2E Claim Verification Tests — Agent Execution Required.

Gate tests (file structure, DB schema, code inspection) have been moved to:
    olav-netops/tests/gates/test_gate_claims.py

This file is reserved for genuine end-to-end tests that exercise agent
invocations via the CLI. These require:
  - A running LLM API (set OPS_NL_E2E_ENABLED=1)
  - Or a live CLAB network (set PROBE_E2E_ENABLED=1)

See tests/e2e/test_ops_nl_e2e.py for NL claim E2E tests.
See tests/e2e/test_diff_netmiko_e2e.py for C-NE-26 real diff E2E.
"""
# Real E2E tests to be added as part of A6 (untested claims).
# Track progress in dev_docs/00. issues.md (claim coverage).
