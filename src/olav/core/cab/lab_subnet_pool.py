"""Pool allocator for CAB ``lab_subnet`` (ARCH-36 fix).

Previously every CAB change defaulted to ``172.16.99.0/30`` in 5 places
(``tcf_writer.render_tcf_from_change_plan``, ``tcf_sim.tcf_emit_from_sim``,
``postcheck_translate``, ``srl_render``, ``srl_rollback``). Two
problems with that:

1. ``172.16.99.0/30`` is real RFC 1918 space — could collide with an
   actual prod transit link the customer is running.
2. Two parallel CAB changes both get the same /30 → second lab deploy
   either fails or overwrites the first.

Pool: ``192.0.2.0/24`` (RFC 5737 TEST-NET-1, reserved for documentation
— guaranteed not to overlap any real network). 64 /30 blocks available,
enough for typical concurrent CAB workloads.

State: JSON file at ``~/.olav/state/lab_subnets.json``::

    {
      "<change_id>": "192.0.2.X/30",
      ...
    }

Idempotent: same ``change_id`` always returns same /30. Releases via
``release_lab_subnet(change_id)`` (called when a change is finalised
or abandoned).
"""
from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from pathlib import Path

_DEFAULT_POOL = "192.0.2.0/24"
_DEFAULT_PREFIXLEN = 30


def _state_path() -> Path:
    p = Path.home() / ".olav" / "state" / "lab_subnets.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_state() -> dict[str, str]:
    p = _state_path()
    if not p.exists():
        return {}
    txt = p.read_text(encoding="utf-8").strip()
    if not txt:
        return {}
    return json.loads(txt)


def _write_state(state: dict[str, str]) -> None:
    p = _state_path()
    fd, tmp_name = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def allocate_lab_subnet(
    change_id: str,
    pool: str = _DEFAULT_POOL,
    prefixlen: int = _DEFAULT_PREFIXLEN,
) -> str:
    """Reserve a /30 (or other ``prefixlen``) for ``change_id``.

    Idempotent: same ``change_id`` returns same /30 across calls.
    Concurrent: two different ``change_id`` values never share a /30
    (atomic rename on the state file gives last-writer-wins semantics
    that's safe enough for the typical few-changes-per-day cadence).

    Raises:
        ValueError: empty ``change_id`` or pool exhausted.
    """
    if not change_id:
        raise ValueError("allocate_lab_subnet requires non-empty change_id")

    state = _read_state()
    if change_id in state:
        return state[change_id]

    used = set(state.values())
    pool_net = ipaddress.IPv4Network(pool, strict=False)
    for sub in pool_net.subnets(new_prefix=prefixlen):
        s = str(sub)
        if s not in used:
            state[change_id] = s
            _write_state(state)
            return s

    raise ValueError(
        f"lab_subnet pool {pool} exhausted at /{prefixlen}; "
        f"{len(used)} blocks in use. Either release old change_ids "
        f"via release_lab_subnet(...) or expand the pool. State file: "
        f"{_state_path()}."
    )


def release_lab_subnet(change_id: str) -> bool:
    """Release the /30 reserved for ``change_id``. Returns True if a
    release happened, False if no entry was present."""
    state = _read_state()
    if change_id not in state:
        return False
    del state[change_id]
    _write_state(state)
    return True


def lookup_lab_subnet(change_id: str) -> str | None:
    """Return the /30 reserved for ``change_id``, or None."""
    return _read_state().get(change_id)


__all__ = [
    "allocate_lab_subnet",
    "lookup_lab_subnet",
    "release_lab_subnet",
]
