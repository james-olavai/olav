"""tcf_load_for_lab — R90 Phase 3 lab-side TCF reader.

Wraps ``olav.core.cab.tcf_load`` + the arg-derivation helpers into
a single MCP tool the ops-lab agent calls right after it receives a
spec path. Returns a JSON envelope with everything the lab needs to
proceed without parsing markdown:

  * change_id / title / intent / risk_class — for the report header
  * device_names — for prompts and references
  * r88_args / r89_args — ready to pass into generate_clab_topology
    + generate_srl_lab_config invokes
  * post_check — list of verification commands to execute
  * tvt — list of test rows (test_id / description / expected /
    severity); the agent fills actual_lab + status during run
  * required_tests / optional_tests — pass-criteria

If the spec is malformed (FK violation, missing required field), the
Pydantic ValidationError surfaces as a clear ``status: error`` —
better than the agent silently assuming defaults.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT and not (_PROJECT_ROOT / "pyproject.toml").exists():
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


from langchain_core.tools import tool


@tool
def tcf_load_for_lab(spec_path: str) -> str:
    """Load a TCF spec and derive everything the lab needs to run.

    Use this AS THE FIRST TOOL in the lab workflow when the user
    points at a TCF (``.tcf.yaml``) file. Replaces the markdown-era
    ``read_file(spec.md)`` + agent extracts facts pattern.

    Args:
        spec_path: Absolute or repo-relative path to a TCF YAML
            file (e.g. ``"exports/cab/cab_001/spec.tcf.yaml"``).

    Returns:
        JSON envelope:
          status: "ok" / "error"
          change_id, title, risk_class, intent (dict)
          device_names: ["R1", "R4", ...]
          r88_args: {nodes: [...], lab_name: ...}   for generate_clab_topology
          r89_args: {nodes, loopbacks, asns, intent_type, lab_subnet?}  for
                    generate_srl_lab_config (null if intent.type unsupported)
          post_check: [{device, check_id, description, command, expected_pattern}, ...]
          tvt: [{test_id, description, expected, severity}, ...]
          required_tests: ["T1", "T2"]
          optional_tests: ["T3"]

        On schema error / FK violation:
          status: "error"
          error: "<readable Pydantic message>"
    """
    try:
        from olav.core.cab import tcf_load, tcf_to_r88_args, tcf_to_r89_args
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"olav.core.cab module unavailable: {type(exc).__name__}: {exc}",
        })

    try:
        tcf = tcf_load(spec_path)
    except FileNotFoundError as exc:
        return json.dumps({
            "status": "error",
            "error": f"TCF file not found: {spec_path}",
            "detail": str(exc),
        })
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"TCF parse failed: {type(exc).__name__}: {exc}",
            "spec_path": str(spec_path),
        })

    # R88 args are always derivable; R89 may not be (intent type might
    # be unsupported — return null and let the agent see the reason)
    r88_args = tcf_to_r88_args(tcf)
    try:
        r89_args = tcf_to_r89_args(tcf)
        r89_error = None
    except ValueError as exc:
        r89_args = None
        r89_error = str(exc)

    return json.dumps({
        "status": "ok",
        "spec_path": str(spec_path),
        "change_id": tcf.change_id,
        "title": tcf.title,
        "risk_class": tcf.risk_class,
        "intent": tcf.intent.model_dump(),
        "device_names": [d.name for d in tcf.devices],
        "devices": [d.model_dump() for d in tcf.devices],
        "r88_args": r88_args,
        "r89_args": r89_args,
        "r89_error": r89_error,
        "post_check": [c.model_dump() for c in tcf.post_check],
        "tvt": [t.model_dump() for t in tcf.tvt],
        "required_tests": tcf.required_tests,
        "optional_tests": tcf.optional_tests,
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    args = json.loads(parsed.args_json)
    print(tcf_load_for_lab.invoke(args))
