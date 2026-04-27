"""TCF file I/O — load + emit.

YAML is the on-disk format (Pydantic handles JSON natively, but
YAML allows comments + multi-line strings which matters for CLI
blocks).

Atomicity: ``tcf_emit`` writes to a sibling temp file then renames.
If the process is killed mid-write, the previous file (if any) is
preserved. Important because lab updates the same file (writing
``lab.*`` fields back) while sim or other readers may also be
active.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .tcf_schema import CabTcf


def tcf_emit(tcf: CabTcf, path: str | Path) -> Path:
    """Write a CabTcf to ``path`` as YAML, atomically.

    Pydantic validates the model before serialisation. If validation
    fails, no file is written.

    Atomic via temp-file + ``os.replace``. The directory must exist;
    the file may or may not.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Pydantic v2 — model_dump(mode="json") returns JSON-safe types
    # (datetime → ISO string, etc.) which YAML can serialise cleanly.
    data = tcf.model_dump(mode="json")

    # Use yaml.safe_dump with sort_keys=False so the schema's logical
    # ordering (envelope first, devices, implementation, ..., lab,
    # prod) is preserved — important for human readability.
    yaml_text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=120,
    )

    # Write to a sibling temp file, then atomically rename. Avoids
    # truncated files if the process is killed mid-write.
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{dest.name}.",
        suffix=".tmp",
        dir=str(dest.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        os.replace(tmp_name, dest)
    except Exception:
        # On any error, clean up the temp file
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

    return dest


def tcf_load(path: str | Path) -> CabTcf:
    """Read + parse + validate a TCF YAML file.

    Pydantic raises ``ValidationError`` (subclass of ValueError) on
    schema mismatch — including the cross-FK validator's output
    when devices/implementation/rollback/post_check references are
    inconsistent.
    """
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"TCF not found: {src}")

    with src.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(
            f"TCF must be a YAML mapping at top level; "
            f"got {type(raw).__name__} from {src}"
        )

    return CabTcf.model_validate(raw)
