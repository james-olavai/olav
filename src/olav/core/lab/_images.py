"""ISSUE-ARCH-38 (P2, 2026-05-12) — single source of truth for lab
container image versions.

Before this module:
    deploy_lab._SRL_IMAGE = "ghcr.io/nokia/srlinux:24.10.1"
    topology._DEFAULT_IMAGE = "ghcr.io/nokia/srlinux:24.10.1"
    (silently overwrote any user-supplied image with the pinned version)

Two problems the previous shape created:
  1. Two hard-coded copies → guaranteed to drift when one was bumped
  2. Silent override of user-supplied images violated POLA — testing a
     new SRL release (e.g. :25.x) required editing source, not config

Resolution order (highest priority first):
  1. ``OLAV_SRL_IMAGE`` env var
  2. ``<lab_workspace>/config/config.json``  key ``srl_image``
  3. Pinned default ``DEFAULT_SRL_IMAGE``

The override logic (deploy_lab.py:182+) used to *silently* overwrite
any user srlinux image whose tag wasn't ``:24.10.1``. That's now a
log warning AND a respect-user policy: we leave the user's image
alone but flag the mismatch.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)


DEFAULT_SRL_IMAGE: Final[str] = "ghcr.io/nokia/srlinux:24.10.1"


def srl_image() -> str:
    """Resolve the SRL container image once per call (cheap I/O).

    Walks the resolution order above. Returns a complete image
    reference (registry/repo:tag).
    """
    env = os.environ.get("OLAV_SRL_IMAGE")
    if env:
        return env.strip()

    # Try lab_workspace/config/config.json — already used by topology
    # for mgmt_subnet etc.
    try:
        from olav.core.lab._paths import lab_config_path
        cfg_path = lab_config_path()
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("srl_image: lab config parse failed: %s", exc)
                cfg = {}
            v = cfg.get("srl_image")
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception as exc:
        logger.debug("srl_image: lab config lookup failed: %s", exc)

    return DEFAULT_SRL_IMAGE


def is_srlinux_image(image: str) -> bool:
    """Loose check: True iff the image reference names a Nokia SRL."""
    if not image:
        return False
    image = image.lower()
    return "srlinux" in image or "/nokia/" in image
