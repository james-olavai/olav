"""
tests/unit/test_keyring_store.py
────────────────────────────────
Unit coverage for src/olav/core/auth/keyring_store.py — the bearer
token secret store used by OLAV CLI.

Guarantees:
  1. `service_name()` is stable, hex-digest-shaped, and depends on the
     users.duckdb path — different paths must produce different service
     names (multi-env isolation).
  2. `save_token()` writes via the real `keyring.set_password` when the
     backend is usable; falls back to the legacy file on backend error
     when `write_file_fallback=True`; raises when `=False`.
  3. `load_token()` resolves OLAV_TOKEN → keyring → legacy file → None
     in that strict priority order.
  4. `clear_token()` removes both the keyring slot and the legacy file.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Install a tiny in-memory keyring stand-in.

    Captures set/get/delete calls in a dict so tests can assert
    round-trip behaviour without touching a real backend.
    """
    storage: dict[tuple[str, str], str] = {}
    errors_mod = types.ModuleType("keyring.errors")

    class _PasswordDeleteError(Exception):
        pass

    errors_mod.PasswordDeleteError = _PasswordDeleteError  # type: ignore[attr-defined]

    def set_password(service: str, username: str, password: str) -> None:
        storage[(service, username)] = password

    def get_password(service: str, username: str) -> str | None:
        return storage.get((service, username))

    def delete_password(service: str, username: str) -> None:
        try:
            del storage[(service, username)]
        except KeyError as exc:
            raise _PasswordDeleteError(str(exc)) from exc

    def get_keyring() -> object:
        class _FakeBackend:
            pass

        return _FakeBackend()

    mod = types.ModuleType("keyring")
    mod.set_password = set_password  # type: ignore[attr-defined]
    mod.get_password = get_password  # type: ignore[attr-defined]
    mod.delete_password = delete_password  # type: ignore[attr-defined]
    mod.get_keyring = get_keyring  # type: ignore[attr-defined]
    mod.errors = errors_mod  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors_mod)

    return types.SimpleNamespace(
        storage=storage,
        set_password=set_password,
        get_password=get_password,
        delete_password=delete_password,
    )


@pytest.fixture
def isolated_legacy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the module-level legacy token path under a tmp dir so
    tests can write/read without polluting the real ``~/.olav/token``."""
    import olav.core.auth.keyring_store as store

    legacy = tmp_path / ".olav" / "token"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(store, "_LEGACY_TOKEN_PATH", legacy)
    return legacy


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no ambient ``OLAV_TOKEN`` leaks into tests, and reset the
    keyring availability probe so stubs installed per-test are honoured."""
    monkeypatch.delenv("OLAV_TOKEN", raising=False)
    monkeypatch.delenv("OLAV_DISABLE_KEYRING", raising=False)
    # Deterministic default username for service-name derivation.
    monkeypatch.setenv("USER", "testuser")
    # The probe cache is module-level; clear it so each test picks up
    # whatever stub it installed.
    import olav.core.auth.keyring_store as store

    store._reset_keyring_probe_cache()


# ── 1. service_name is stable + per-workspace ───────────────────────────────


def test_service_name_is_deterministic(tmp_path: Path) -> None:
    from olav.core.auth.keyring_store import service_name

    db_a = tmp_path / "a" / "users.duckdb"
    db_b = tmp_path / "b" / "users.duckdb"
    for p in (db_a, db_b):
        p.parent.mkdir(parents=True, exist_ok=True)

    name_a1 = service_name(db_a)
    name_a2 = service_name(db_a)
    name_b = service_name(db_b)

    assert name_a1 == name_a2
    assert name_a1 != name_b
    assert name_a1.startswith("olav:")
    # 12-hex-digest suffix
    assert len(name_a1.split(":", 1)[1]) == 12


# ── 2. save_token round-trip ────────────────────────────────────────────────


def test_save_token_writes_to_keyring(
    fake_keyring: types.SimpleNamespace,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    from olav.core.auth.keyring_store import save_token, service_name

    db = tmp_path / "users.duckdb"
    where = save_token("olav_abc123", users_db_path=db)

    assert where == "keyring"
    assert fake_keyring.storage[(service_name(db), "testuser")] == "olav_abc123"
    # Keyring success clears any stale legacy file.
    assert not isolated_legacy.exists()


def test_save_token_falls_back_to_per_env_file_on_backend_error(
    monkeypatch: pytest.MonkeyPatch,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    # Install a keyring stub whose set_password always raises — but
    # whose get_password returns None quickly so the probe succeeds.
    mod = types.ModuleType("keyring")

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("no daemon")

    mod.set_password = _boom  # type: ignore[attr-defined]
    mod.get_password = lambda *a, **kw: None  # type: ignore[attr-defined]
    mod.delete_password = _boom  # type: ignore[attr-defined]
    mod.get_keyring = lambda: object()  # type: ignore[attr-defined]
    errors_mod = types.ModuleType("keyring.errors")

    class _PDE(Exception):
        pass

    errors_mod.PasswordDeleteError = _PDE  # type: ignore[attr-defined]
    mod.errors = errors_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors_mod)

    from olav.core.auth.keyring_store import _per_env_token_path, save_token

    db = tmp_path / "users.duckdb"
    where = save_token("olav_xyz", users_db_path=db)

    assert where == "file"
    # Write landed in the per-env location, not the user-global legacy.
    assert _per_env_token_path(db).read_text().strip() == "olav_xyz"
    assert not isolated_legacy.exists()


def test_save_token_raises_when_fallback_disabled(
    monkeypatch: pytest.MonkeyPatch,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    mod = types.ModuleType("keyring")

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("no daemon")

    mod.set_password = _boom  # type: ignore[attr-defined]
    mod.get_password = lambda *a, **kw: None  # type: ignore[attr-defined]
    mod.delete_password = _boom  # type: ignore[attr-defined]
    mod.get_keyring = lambda: object()  # type: ignore[attr-defined]
    errors_mod = types.ModuleType("keyring.errors")

    class _PDE(Exception):
        pass

    errors_mod.PasswordDeleteError = _PDE  # type: ignore[attr-defined]
    mod.errors = errors_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors_mod)

    from olav.core.auth.keyring_store import save_token

    with pytest.raises(RuntimeError):
        save_token(
            "olav_xyz",
            users_db_path=tmp_path / "users.duckdb",
            write_file_fallback=False,
        )
    assert not isolated_legacy.exists()


# ── 3. load_token resolution order ──────────────────────────────────────────


def test_load_token_env_wins_over_keyring_and_file(
    monkeypatch: pytest.MonkeyPatch,
    fake_keyring: types.SimpleNamespace,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    from olav.core.auth.keyring_store import load_token, service_name

    db = tmp_path / "users.duckdb"
    fake_keyring.set_password(service_name(db), "testuser", "KEY_TOKEN")
    isolated_legacy.write_text("FILE_TOKEN\n", encoding="utf-8")
    monkeypatch.setenv("OLAV_TOKEN", "ENV_TOKEN")

    assert load_token(users_db_path=db) == "ENV_TOKEN"


def test_load_token_keyring_wins_over_file(
    fake_keyring: types.SimpleNamespace,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    from olav.core.auth.keyring_store import load_token, service_name

    db = tmp_path / "users.duckdb"
    fake_keyring.set_password(service_name(db), "testuser", "KEY_TOKEN")
    isolated_legacy.write_text("FILE_TOKEN\n", encoding="utf-8")

    assert load_token(users_db_path=db) == "KEY_TOKEN"


def test_load_token_file_used_when_keyring_empty(
    fake_keyring: types.SimpleNamespace,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    from olav.core.auth.keyring_store import load_token

    db = tmp_path / "users.duckdb"
    isolated_legacy.write_text("FILE_TOKEN\n", encoding="utf-8")

    assert load_token(users_db_path=db) == "FILE_TOKEN"


def test_load_token_returns_none_when_nothing_configured(
    fake_keyring: types.SimpleNamespace,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    from olav.core.auth.keyring_store import load_token

    db = tmp_path / "users.duckdb"
    # No env var, empty keyring, no legacy file.
    assert load_token(users_db_path=db) is None


# ── 4. clear_token ──────────────────────────────────────────────────────────


def test_clear_token_removes_keyring_and_files(
    fake_keyring: types.SimpleNamespace,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    from olav.core.auth.keyring_store import (
        _per_env_token_path,
        clear_token,
        service_name,
    )

    db = tmp_path / "users.duckdb"
    fake_keyring.set_password(service_name(db), "testuser", "KEY_TOKEN")
    isolated_legacy.write_text("FILE_TOKEN\n", encoding="utf-8")
    per_env = _per_env_token_path(db)
    per_env.parent.mkdir(parents=True, exist_ok=True)
    per_env.write_text("PER_ENV_TOKEN\n", encoding="utf-8")

    clear_token(users_db_path=db)

    assert (service_name(db), "testuser") not in fake_keyring.storage
    assert not isolated_legacy.exists()
    assert not per_env.exists()


def test_clear_token_is_idempotent(
    fake_keyring: types.SimpleNamespace,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    from olav.core.auth.keyring_store import clear_token

    db = tmp_path / "users.duckdb"
    # Nothing to clear — must not raise.
    clear_token(users_db_path=db)
    clear_token(users_db_path=db)


# ── 5. probe — hanging backend is treated as unavailable ────────────────────


def test_probe_hanging_backend_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    """On headless systems ``keyring.get_password`` can block on DBus.

    The probe wraps the call in a thread with a 1s timeout and returns
    False on timeout so ``load_token`` falls back to the legacy file
    instead of hanging the TUI.
    """
    import threading

    mod = types.ModuleType("keyring")

    def _hang(*args: object, **kwargs: object) -> None:
        # Block until the test teardown; the daemon thread will be
        # killed when the interpreter exits.
        threading.Event().wait()

    mod.get_password = _hang  # type: ignore[attr-defined]
    mod.set_password = _hang  # type: ignore[attr-defined]
    mod.delete_password = _hang  # type: ignore[attr-defined]
    mod.get_keyring = lambda: object()  # type: ignore[attr-defined]
    errors_mod = types.ModuleType("keyring.errors")

    class _PDE(Exception):
        pass

    errors_mod.PasswordDeleteError = _PDE  # type: ignore[attr-defined]
    mod.errors = errors_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors_mod)

    # Shorten the probe timeout so the test runs quickly.
    import olav.core.auth.keyring_store as store

    monkeypatch.setattr(store, "_KEYRING_PROBE_TIMEOUT_SECONDS", 0.1)
    store._reset_keyring_probe_cache()

    # With a hanging backend, load_token must not hang — it returns the
    # legacy file content (or None) instead.
    isolated_legacy.write_text("FILE_TOKEN\n", encoding="utf-8")
    db = tmp_path / "users.duckdb"

    assert store.load_token(users_db_path=db) == "FILE_TOKEN"
    # Second call is cached — no further probe.
    assert store.load_token(users_db_path=db) == "FILE_TOKEN"


def test_probe_disabled_by_env_var(
    monkeypatch: pytest.MonkeyPatch,
    fake_keyring: types.SimpleNamespace,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    """``OLAV_DISABLE_KEYRING=1`` forces the file path, even when the
    keyring backend is perfectly healthy — for CI and opt-out use."""
    from olav.core.auth.keyring_store import (
        _per_env_token_path,
        load_token,
        save_token,
        service_name,
    )

    db = tmp_path / "users.duckdb"
    # Prime the keyring so file-fallback is distinguishable.
    fake_keyring.set_password(service_name(db), "testuser", "KEY_TOKEN")

    monkeypatch.setenv("OLAV_DISABLE_KEYRING", "1")
    import olav.core.auth.keyring_store as store

    store._reset_keyring_probe_cache()

    # With keyring disabled, load sees only the file (nothing there yet).
    assert load_token(users_db_path=db) is None

    # Writes go to the per-env file, not the user-global legacy.
    where = save_token("olav_new", users_db_path=db)
    assert where == "file"
    assert _per_env_token_path(db).read_text().strip() == "olav_new"
    assert not isolated_legacy.exists()


# ── 6. per-env file wins over legacy on read ────────────────────────────────


def test_load_token_per_env_wins_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    """A per-env token file must shadow any stale ~/.olav/token — the
    whole point of per-env isolation on headless systems."""
    monkeypatch.setenv("OLAV_DISABLE_KEYRING", "1")
    import olav.core.auth.keyring_store as store

    store._reset_keyring_probe_cache()

    db = tmp_path / "env-a" / "databases" / "users.duckdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    per_env = store._per_env_token_path(db)
    per_env.write_text("PER_ENV\n", encoding="utf-8")
    isolated_legacy.write_text("LEGACY\n", encoding="utf-8")

    assert store.load_token(users_db_path=db) == "PER_ENV"


def test_load_token_falls_back_to_legacy_when_per_env_absent(
    monkeypatch: pytest.MonkeyPatch,
    isolated_legacy: Path,
    tmp_path: Path,
) -> None:
    """Pre-keyring installs keep working: no per-env file, keyring
    unavailable → legacy ~/.olav/token is read."""
    monkeypatch.setenv("OLAV_DISABLE_KEYRING", "1")
    import olav.core.auth.keyring_store as store

    store._reset_keyring_probe_cache()

    db = tmp_path / "env-b" / "databases" / "users.duckdb"
    isolated_legacy.write_text("LEGACY_ONLY\n", encoding="utf-8")

    assert store.load_token(users_db_path=db) == "LEGACY_ONLY"
