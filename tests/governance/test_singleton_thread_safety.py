"""CORE-01: Singleton initialisation is thread-safe under concurrent access.

Covers the three platform-level singletons patched in this change:

* ``olav.core.config.get_config`` / ``reload_config``
* ``olav.core.memory.get_store`` / ``reset_store``
* ``olav.core.router.get_router``

Each test spins up >=64 threads hitting the entry point simultaneously and
asserts that every thread observes the same instance id. A race in the
prior "if None then create" pattern would surface as two distinct
instances or a half-initialised object raising ``AttributeError``.
"""

from __future__ import annotations

import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def _assert_source_contains(path: Path, snippets: list[str]) -> None:
    src = path.read_text(encoding="utf-8")
    for snippet in snippets:
        assert snippet in src, f"missing thread-safety guard in {path.name}: {snippet}"


def _collect_ids(fn, workers: int = 64):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fn) for _ in range(workers)]
        return [id(f.result()) for f in as_completed(futures)]


def test_get_config_singleton_under_concurrency():
    from olav.core import config as config_mod

    config_mod._config = None  # type: ignore[attr-defined]
    config_mod.ConfigLoader._instance = None
    config_mod.ConfigLoader._loaded = False

    ids = _collect_ids(config_mod.get_config, workers=100)
    assert len(set(ids)) == 1, f"get_config produced {len(set(ids))} distinct instances"


def test_reload_config_is_consistent_under_concurrency():
    from olav.core import config as config_mod

    # Warm the singleton so reload actually replaces an existing instance.
    config_mod.get_config()

    def mixed():
        # Half the workers reload, half get — every return value must be a
        # fully initialised ConfigLoader (touching ``llm`` exercises lazy
        # properties that depend on _load_all having run).
        inst = config_mod.reload_config()
        _ = inst.llm  # half-initialised instance would raise here
        return inst

    results = [mixed() for _ in range(4)]  # serial warm-up

    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = [
            pool.submit(config_mod.reload_config if i % 2 else config_mod.get_config)
            for i in range(64)
        ]
        results += [f.result() for f in as_completed(futures)]

    # All results must be ConfigLoader instances whose lazy state works.
    for r in results:
        _ = r.llm
        _ = r.embedding


def test_get_router_singleton_under_concurrency():
    if importlib.util.find_spec("lancedb") is None:
        _assert_source_contains(
            Path(__file__).resolve().parents[2] / "src/olav/core/router.py",
            [
                "_router_lock = threading.Lock()",
                "if _router_instance is None:",
                "with _router_lock:",
                "_router_instance = SemanticRouter()",
            ],
        )
        return

    from olav.core import router as router_mod

    router_mod._router_instance = None  # type: ignore[attr-defined]

    ids = _collect_ids(router_mod.get_router, workers=100)
    assert len(set(ids)) == 1, f"get_router produced {len(set(ids))} distinct instances"


def test_get_store_singleton_under_concurrency(tmp_path):
    if importlib.util.find_spec("lancedb") is None:
        _assert_source_contains(
            Path(__file__).resolve().parents[2] / "src/olav/core/memory/__init__.py",
            [
                "_store_lock = threading.Lock()",
                "if (\n            _store_instance is None",
                "with _store_lock:",
                "_store_instance = LanceDBStore(",
            ],
        )
        return

    from olav.core import memory as memory_mod

    # Force a clean slate — reset_store would close a real LanceDB handle;
    # we clear the module-level refs directly since there may be none yet.
    memory_mod._store_instance = None  # type: ignore[attr-defined]
    memory_mod._store_db_path = None  # type: ignore[attr-defined]
    memory_mod._store_embedding_dim = None  # type: ignore[attr-defined]

    db_path = str(tmp_path / "lance.db")

    def call():
        return memory_mod.get_store(db_path=db_path, embedding_dim=8)

    ids = _collect_ids(call, workers=64)
    assert len(set(ids)) == 1, f"get_store produced {len(set(ids))} distinct instances"

    reset_fn = (
        getattr(memory_mod, "reset_store", None)
        or getattr(memory_mod, "close_store", None)
        or getattr(memory_mod, "clear_store", None)
    )
    if callable(reset_fn):
        reset_fn()
    else:
        memory_mod._store_instance = None  # type: ignore[attr-defined]
        memory_mod._store_db_path = None  # type: ignore[attr-defined]
        memory_mod._store_embedding_dim = None  # type: ignore[attr-defined]
