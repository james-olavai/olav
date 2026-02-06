#!/usr/bin/env python3
"""Check DeepAgents create_deep_agent API signature."""

import inspect
from deepagents import create_deep_agent

sig = inspect.signature(create_deep_agent)
print("create_deep_agent() parameters:")
print("=" * 60)
for name, param in sig.parameters.items():
    print(f"{name:20s}: {param.annotation}")
    if param.default != inspect.Parameter.empty:
        print(f"{'':20s}  default={param.default}")
