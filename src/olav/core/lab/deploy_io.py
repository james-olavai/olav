"""Lab deployment I/O helpers — save configs + destroy lab.

Per ADR-0008 rev1 (R92.6): these were @tool wrappers; folded into
Python helpers because subprocess scripts can call CLAB REST and
write workspace files just as well, and OLAV holds no cross-call
in-process state for these operations.

Public surface:
    * ``save_lab_config(lab_name, node, config_lines) -> dict``
    * ``destroy_lab(lab_name, *, timeout=30.0) -> dict``

Both return dict envelopes with ``status``/``error`` so skill-script
callers can serialise as JSON for stdout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ._paths import lab_config_path


def save_lab_config(
    lab_name: str,
    node: str,
    config_lines: list[str],
) -> dict[str, Any]:
    """Save SR Linux config lines for a lab node to a temp dropbox file.

    The dropbox path is ``<EXPORTS_DIR>/lab/<lab_name>/<node>.json``.
    ``deploy_and_push_lab`` reads from the same path when its
    ``configs`` arg is empty.
    """
    if not config_lines:
        return {
            "saved": False,
            "error": "config_lines is empty — provide all SRL set commands for this node",
            "node": node,
        }

    try:
        from olav.core.config import EXPORTS_DIR
        out_dir = EXPORTS_DIR / "lab" / lab_name
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{node}.json"
        path.write_text(
            json.dumps(config_lines, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        return {"saved": False, "error": str(exc), "node": node}

    return {
        "saved": True,
        "node": node,
        "lab_name": lab_name,
        "lines": len(config_lines),
        "path": str(path),
        "message": (
            f"Config for {node} saved ({len(config_lines)} lines). "
            f"Save remaining nodes, then call deploy_and_push_lab."
        ),
    }


def _bootstrap_clab_env(config_path: Path) -> None:
    """Best-effort CLAB credential bootstrap from workspace config.

    The privilege model is the same as the @tool wrapper — we
    inherit env when set, fall back to workspace JSON config.
    """
    if os.environ.get("CLAB_USERNAME") and os.environ.get("CLAB_PASSWORD"):
        return
    try:
        cfg = json.loads(config_path.read_text())
        os.environ.setdefault("CLAB_USERNAME", cfg.get("username", "admin"))
        os.environ.setdefault("CLAB_PASSWORD", cfg.get("password", "clab"))
    except Exception:
        pass


def destroy_lab(
    lab_name: str,
    *,
    timeout: float = 30.0,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Destroy a ContainerLab lab via the remote CLAB REST API.

    404 (lab not found) is treated as success — the lab is already
    gone, which is the desired end state.

    ``config_path`` defaults to
    ``<workspace>/ops/lab/config/config.json``. Skill-script callers
    can override.
    """
    cfg = (
        Path(config_path) if config_path else lab_config_path()
    )
    _bootstrap_clab_env(cfg)

    try:
        from olav.platform.services.client import service_call
    except Exception as exc:
        return {
            "status": "error",
            "error": f"service_call unavailable: {type(exc).__name__}: {exc}",
            "lab_name": lab_name,
        }

    try:
        body = service_call(
            "containerlab",
            method="DELETE",
            path=f"/api/v1/labs/{lab_name}",
            confirmed=True,
            timeout=float(timeout),
        )
    except Exception as exc:
        err = str(exc)
        if "404" in err or "not found" in err.lower():
            return {
                "status": "ok",
                "destroyed": True,
                "lab_name": lab_name,
                "detail": "Lab not found (already destroyed or never existed)",
            }
        return {
            "status": "error",
            "error": err,
            "lab_name": lab_name,
        }

    if isinstance(body, dict) and body.get("status") == "requires_approval":
        return {
            "status": "error",
            "error": "service_call requires approval",
            "lab_name": lab_name,
        }

    return {
        "status": "ok",
        "destroyed": True,
        "lab_name": lab_name,
        "detail": body if isinstance(body, (str, dict)) else str(body),
    }
