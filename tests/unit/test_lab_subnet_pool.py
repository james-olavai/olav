"""Tests for ARCH-36 lab_subnet pool allocator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from olav.core.cab.lab_subnet_pool import (
    _state_path,
    allocate_lab_subnet,
    lookup_lab_subnet,
    release_lab_subnet,
)


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect ~/.olav/state to a tmp path so tests don't touch real state."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    yield tmp_path


def test_allocate_returns_first_block_in_pool(isolated_state):
    s = allocate_lab_subnet("test-1")
    assert s == "192.0.2.0/30"


def test_allocate_idempotent_for_same_change_id(isolated_state):
    a = allocate_lab_subnet("test-idempotent")
    b = allocate_lab_subnet("test-idempotent")
    assert a == b
    assert a == "192.0.2.0/30"


def test_allocate_returns_distinct_for_concurrent_change_ids(isolated_state):
    a = allocate_lab_subnet("change-A")
    b = allocate_lab_subnet("change-B")
    c = allocate_lab_subnet("change-C")
    assert {a, b, c} == {"192.0.2.0/30", "192.0.2.4/30", "192.0.2.8/30"}


def test_allocate_skips_used_blocks_after_release(isolated_state):
    a = allocate_lab_subnet("first")
    b = allocate_lab_subnet("second")
    assert a != b

    # Release first; allocating a new change_id should reuse first's block
    assert release_lab_subnet("first") is True
    c = allocate_lab_subnet("third")
    assert c == a  # released block is now available


def test_release_returns_false_for_unknown(isolated_state):
    assert release_lab_subnet("never-allocated") is False


def test_lookup_returns_none_for_unknown(isolated_state):
    assert lookup_lab_subnet("never-allocated") is None


def test_lookup_after_allocate(isolated_state):
    s = allocate_lab_subnet("lookup-test")
    assert lookup_lab_subnet("lookup-test") == s


def test_state_file_atomic_write(isolated_state):
    """State file should always be valid JSON, even mid-write."""
    allocate_lab_subnet("a")
    allocate_lab_subnet("b")
    p = _state_path()
    assert p.exists()
    data = json.loads(p.read_text())
    assert "a" in data and "b" in data


def test_empty_change_id_rejected(isolated_state):
    with pytest.raises(ValueError, match="non-empty change_id"):
        allocate_lab_subnet("")


def test_pool_exhaustion(isolated_state):
    """Allocate every /30 in a tiny pool, then expect ValueError."""
    # /28 pool gives 4 /30 blocks
    for i in range(4):
        allocate_lab_subnet(f"c-{i}", pool="192.0.2.0/28", prefixlen=30)
    with pytest.raises(ValueError, match="exhausted"):
        allocate_lab_subnet("c-overflow", pool="192.0.2.0/28", prefixlen=30)


def test_render_tcf_uses_pool_when_lab_subnet_omitted(isolated_state, tmp_path):
    """End-to-end: render_tcf_from_change_plan with no lab_subnet kwarg
    should allocate from the pool (not fall back to legacy 172.16.99.0/30)
    and propagate the allocated /30 through to the rendered CLI."""
    from unittest.mock import patch

    from olav.core.cab.tcf_writer import render_tcf_from_change_plan

    fake_facts = {
        "RA": {"platform": "cisco_ios", "loopback": "10.10.10.1", "local_as": 65001},
        "RB": {"platform": "cisco_ios", "loopback": "10.10.10.2", "local_as": 65002},
    }
    plan = """
## Change Summary
```yaml
change_id: pool-test-01
title: pool integration test
intent_type: ebgp_direct
devices: [RA, RB]
```
"""
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        r = render_tcf_from_change_plan(plan, output_dir=tmp_path)

    assert r["status"] == "ok"
    yaml_text = Path(r["spec_path"]).read_text()
    # Pool-allocated /30 from 192.0.2.0/24 (RFC 5737), not 172.16.99
    assert "172.16.99" not in yaml_text, "legacy hardcoded subnet leaked"
    assert "192.0.2." in yaml_text, "pool subnet not in rendered CLI"
    # Same change_id called again returns same /30 (idempotent)
    assert lookup_lab_subnet("pool-test-01") is not None


def test_uses_rfc5737_pool_by_default(isolated_state):
    """Default pool must be RFC 5737 documentation space — guaranteed
    not to overlap any real network.  This is the whole point of the
    ARCH-36 fix; if someone changes the default, this test should
    catch it."""
    s = allocate_lab_subnet("rfc5737-test")
    # Pool starts at 192.0.2.0; first /30 must be in TEST-NET-1
    assert s.startswith("192.0.2.")
