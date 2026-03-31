#!/usr/bin/env python3
"""
Python Simulation Tool — Wraps LLMExperimentSandbox for deterministic What-If analysis.

Replaces:
  - ops-simulation/tools/simulate_change.py  (NetworkSimulator-backed, imperative)
  - ops-simulation/tools/analyze_network_topology.py  (DuckPGQ-based)

The LLM writes Python code that runs inside a fully isolated subprocess. The sandbox
exposes:
  - db        : read-only DatabaseProxy (db.query(sql) → list[dict])
  - sim       : SimulationProxy — writable in-memory DuckDB clone (sim.clone / sim.execute)
  - nx        : networkx — graph engine for path / reachability analysis
  - netutils  : netutils — IP math, interface normalization, prefix overlap checks

The LLM code MUST set _result to a JSON-serialisable dict before finishing.

Usage in DeepAgents:
    from .tools import run_python_simulation
    agent = create_deep_agent(tools=[run_python_simulation.run_python_simulation])
"""

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_ROOT = _find_project_root()
sys.path.insert(0, str(_ROOT / "src"))

from olav.core.config import MAIN_DB_PATH
from olav.core.simulation.llm_sandbox import LLMExperimentSandbox


def _run_sandbox(coro) -> Any:
    """Run a coroutine regardless of whether we're inside a running event loop.

    LangChain tools are invoked in a running async loop, so asyncio.run() would
    raise 'This event loop is already running'.  We fall back to running the
    coroutine in a dedicated daemon thread with its own event loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're inside a running loop — spin up a new thread with its own loop
        result_container: list[Any] = []
        exc_container: list[BaseException] = []

        def _target():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result_container.append(new_loop.run_until_complete(coro))
            except Exception as exc:
                exc_container.append(exc)
            finally:
                new_loop.close()

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=600)  # 10-min hard cap
        if exc_container:
            raise exc_container[0]
        if not result_container:
            raise TimeoutError("Sandbox thread timed out (>600s)")
        return result_container[0]
    else:
        return asyncio.run(coro)


class RunPythonSimulationInput(BaseModel):
    """Input for run_python_simulation tool."""

    experiment_code: str = Field(
        ...,
        description=(
            "Python code to execute inside the sandbox. "
            "Must set `_result` to a JSON-serialisable dict. "
            "Available globals: db, sim, nx, netutils, json, math, itertools, collections."
        ),
    )
    experiment_name: str = Field(
        default="simulation",
        description="Short label for the experiment (used for work-dir naming and logs).",
    )
    timeout: int = Field(
        default=120,
        description="Execution timeout in seconds (default 120).",
    )


class RunPythonSimulationOutput(BaseModel):
    """Output of run_python_simulation tool."""

    status: str = Field(..., description="'success' or 'error'")
    result: Any = Field(default=None, description="Value of _result set by experiment_code")
    error: str | None = Field(default=None, description="Error message if status == 'error'")
    error_trace: str | None = Field(default=None, description="Full traceback if available")
    execution_time: float = Field(default=0.0, description="Wall-clock seconds")
    work_dir: str | None = Field(default=None, description="Sandbox work directory path")


def main(params: dict) -> dict:
    """Execute a Python simulation experiment in the LLMExperimentSandbox.

    Args:
        params: {
            "experiment_code": "<python code string>",   # required
            "experiment_name": "my_sim",                 # optional
            "timeout": 120                               # optional
        }

    Returns:
        RunPythonSimulationOutput as dict
    """
    try:
        args = RunPythonSimulationInput(**params)
    except Exception as e:
        return RunPythonSimulationOutput(
            status="error",
            error=f"Invalid input parameters: {e}",
        ).model_dump()

    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))

    try:
        exec_result = _run_sandbox(
            sandbox.execute_experiment(
                experiment_code=args.experiment_code,
                experiment_name=args.experiment_name,
                timeout=args.timeout,
            )
        )
    except Exception as e:
        return RunPythonSimulationOutput(
            status="error",
            error=f"Sandbox execution failed: {e}",
        ).model_dump()

    work_dir_str = None
    if exec_result.artifacts:
        wd = exec_result.artifacts.get("work_dir")
        work_dir_str = str(wd) if wd else None

    return RunPythonSimulationOutput(
        status=exec_result.status,
        result=exec_result.result,
        error=exec_result.error,
        error_trace=exec_result.error_trace,
        execution_time=exec_result.execution_time,
        work_dir=work_dir_str,
    ).model_dump()


@tool
def run_python_simulation(
    experiment_code: str,
    experiment_name: str = "simulation",
    timeout: int = 120,
) -> dict[str, Any]:
    """
    Execute deterministic Python code in an isolated sandbox for What-If analysis.

    The sandbox exposes:
      - `db`       — read-only production DB proxy: db.query(sql) -> list[dict]
      - `sim`      — writable in-memory DuckDB clone:
                       sim.clone(['topology_links', 'ospf_neighbors', ...])
                       sim.execute(sql, params=None)
      - `nx`       — networkx for graph path / reachability analysis
      - `netutils` — IP math, interface name normalization, prefix overlap
      - `json`, `math`, `itertools`, `collections` — standard library

    IMPORTANT: Your code MUST assign a JSON-serialisable dict to `_result` before finishing.

    Quickstart pattern (schema discovery first):
    ```python
    # 1. Discover schema
    all_tables = db.query(
        "SELECT table_name, column_name, data_type "
        "FROM information_schema.columns WHERE table_schema IN ('main', 'netops') "
        "ORDER BY table_name, ordinal_position"
    )
    # 2. Clone needed tables
    sim.clone(['topology_links', 'ospf_neighbors', 'routes'])
    # 3. Mutate for What-If
    sim.execute("UPDATE sim_topology_links SET link_status = 'down' WHERE source_device = ?", ['R2'])
    # 4. Build networkx graph & analyse
    import networkx as nx
    links = sim.execute("SELECT source_device, destination_device FROM sim_topology_links WHERE link_status = 'active'").fetchall()
    G = nx.DiGraph()
    G.add_edges_from(links)
    _result = {"path": nx.shortest_path(G, "R1", "R4") if nx.has_path(G, "R1", "R4") else None}
    ```

    Args:
        experiment_code: Python code string to execute.
        experiment_name: Short label for sandbox workspace directory.
        timeout: Execution timeout in seconds (default 120).

    Returns:
        {"status": "success"|"error", "result": <_result value>, "error": ..., "execution_time": ...}
    """
    return main({
        "experiment_code": experiment_code,
        "experiment_name": experiment_name,
        "timeout": timeout,
    })
