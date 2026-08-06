"""One synthetic database per session, so the gates run instead of skipping.

Before this, every gate module opened `main.duckdb` at import time and marked
itself `skipif` when it was empty. In CI it is always empty, so 74 of 74 tests
skipped on every run — and three suites in the netops half stayed broken for
months because a skip and a pass are indistinguishable in a summary line.

The database is built once per session by `fixture_db.build`, which writes
synthetic rows and then hands the connection to the product's own
`finalise_ingest` to create the views. Gates therefore assert on shipped view
SQL against data that is small enough to reason about.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.gates.fixture_db import build


@pytest.fixture(scope="session")
def netops_db(tmp_path_factory) -> Path:
    """Path to a freshly built synthetic netops database."""
    return build(tmp_path_factory.mktemp("gates") / "main.duckdb")


@pytest.fixture(scope="session")
def con(netops_db: Path):
    """Read-only connection to the fixture database.

    Read-only on purpose: a gate that mutates the fixture would make the next
    test's result depend on execution order, which is exactly the kind of
    hidden coupling these suites exist to catch elsewhere.
    """
    import duckdb

    connection = duckdb.connect(str(netops_db), read_only=True)
    try:
        yield connection
    finally:
        connection.close()
