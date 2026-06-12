"""netops_init/run.py must be loadable via spec_from_file_location.

``olav-netops/scripts/netops_init.py`` (the CLI entrypoint) loads the
workspace ``run.py`` via ``importlib.util.spec_from_file_location`` —
there is no parent package, so every ``from .checkpoint import ...``
line inside ``run.py`` would raise ``ImportError: attempted relative
import with no known parent package``.

The file now guards each relative import with a ``try/except ImportError``
fallback that adds its own directory to ``sys.path`` and re-imports
``checkpoint`` absolutely. This test keeps that wiring intact so a future
refactor cannot silently regress T2-01 / T2-04 / T2-08 (Round 63 fix).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.governance._paths import NETOPS_INIT_DIR


REPO = Path(__file__).resolve().parents[2]
RUN_PY_CANONICAL = NETOPS_INIT_DIR / "run.py"
RUN_PY_PACKAGED = REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "netops_init" / "run.py"


def test_canonical_run_py_loads_standalone():
    """The source-of-truth ``run.py`` must load via spec_from_file_location."""
    assert RUN_PY_CANONICAL.exists(), f"{RUN_PY_CANONICAL} missing"
    spec = importlib.util.spec_from_file_location("_netops_probe", str(RUN_PY_CANONICAL))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    # Executing the module triggers import-time code. If any `from .checkpoint`
    # is not guarded, this raises ImportError.
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    # Sanity — the pipeline-entry symbols we depend on survived.
    assert hasattr(mod, "_run_collection"), "run.py missing _run_collection entrypoint"
    assert hasattr(mod, "_load_devices"), "run.py missing _load_devices helper"


def test_packaged_run_py_matches_canonical_import_guards():
    """The olav-netops-packaged copy must carry the same ImportError guards."""
    if not RUN_PY_PACKAGED.exists():
        # Older checkouts may not have synced yet; don't fail CI, just skip.
        import pytest

        pytest.skip(f"{RUN_PY_PACKAGED} not present in this checkout")

    packaged = RUN_PY_PACKAGED.read_text(encoding="utf-8")
    # Both relative-import sites must be wrapped; verify the sentinel comment
    # that the fallback adds.
    assert "Loaded via importlib.spec_from_file_location" in packaged, (
        "olav-netops packaged run.py is out-of-sync with canonical "
        "— sync it via `cp .olav/workspace/ops/netops_init/* "
        "olav-netops/.olav/workspace/netops/netops_init/` and rebuild the wheel."
    )
    # And both sites must use the try/except ImportError pattern.
    assert packaged.count("except ImportError:") >= 2, (
        "packaged run.py no longer has two ImportError fallbacks; "
        "spec_from_file_location loading will regress."
    )
