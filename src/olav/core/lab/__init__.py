"""R88-A / R89 / R90 deterministic lab generators — Python API.

Per ADR-0007 (Python-first tool architecture), these used to be MCP
``@tool``-decorated wrappers in
``olav-netops/.olav/workspace/ops/lab/tools/``. The MCP layer was
prompt-bloat with no real benefit — the deterministic core is Python
in this module, and agents call it via ``run_python_simulation``
guided by the ``cab_validation_workflow`` expert/usage YAML.

Public functions (each returns a JSON string for sandbox / direct
use; sandbox callers do ``json.loads(...)``):

* :func:`olav.core.lab.topology.generate_clab_topology` — R88-A
  (CLAB topology yaml from netops.v_l2_links_auto)
* :func:`olav.core.lab.srl_render.generate_srl_lab_config` — R89
  (per-node SRL CLI from intent + 3 parallel device arrays)
* :func:`olav.core.lab.srl_rollback.generate_srl_rollback_config` —
  R90 Phase 6 (per-node SRL ``delete /`` CLI for rollback validation)

CAB / TCF integration lives in :mod:`olav.core.cab`. The lab uses
both modules together in the sandbox: ``tcf_load(spec_path)`` →
``tcf_to_r88_args(tcf)`` → ``generate_clab_topology(**args)`` etc.
"""

from .deploy_and_push import deploy_and_push_lab
from .deploy_io import destroy_lab, save_lab_config
from .deploy_lab import deploy_lab
from .push_node_config import push_node_config
from .spec_footer import append_validation_footer
from .srl_render import generate_srl_lab_config
from .srl_rollback import generate_srl_rollback_config
from .topology import generate_clab_topology

__all__ = [
    "append_validation_footer",
    "deploy_and_push_lab",
    "deploy_lab",
    "destroy_lab",
    "generate_clab_topology",
    "generate_srl_lab_config",
    "generate_srl_rollback_config",
    "push_node_config",
    "save_lab_config",
]
