"""Secret-store layer for OLAV CLI bearer tokens.

Historically OLAV wrote the admin token in plaintext to ``~/.olav/token``
with ``chmod 600``.  That works on single-user dev machines but has
three weaknesses:

1. ``~/.olav/token`` is a user-global file, so two OLAV environments
   (dev vs demo) on the same machine clobber each other — whichever was
   ``olav init``'d last wins, silently.
2. ``chmod 600`` relies on filesystem perms only.  ``root``, backups,
   and process-scraping tools can still read it.
3. ``admin rotate-token`` prints the new token to stdout.  The caller
   usually has to remember to copy it into ``~/.olav/token``; a typo
   means the old file is stale while the DB has a new hash.

This module consolidates the read/write path behind three functions
that prefer the OS keyring (Linux ``libsecret`` / macOS Keychain /
Windows Credential Manager via the ``keyring`` package) and gracefully
fall back to ``~/.olav/token`` when no keyring backend is available
(headless CI, minimal containers, …).

Service-name policy
-------------------
Tokens are keyed by the *absolute path of the users.duckdb* they
authenticate against, hashed to a short prefix.  Two workspaces with
different ``.olav/databases/users.duckdb`` paths therefore occupy
disjoint keyring slots, eliminating the cross-env clobber.

Read resolution order
---------------------
1. ``OLAV_TOKEN`` env var — highest priority, used by CI and
   ``--header`` overrides.
2. OS keyring at ``(<service>, <username>)``.
3. ``~/.olav/token`` — back-compat for pre-keyring installs.  Not
   written to once the keyring is available.
4. ``None`` when no source yields a token.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_SERVICE_PREFIX = "olav"
"""Prefix for the keyring service name; disambiguated per-workspace."""

_LEGACY_TOKEN_PATH = Path.home() / ".olav" / "token"
"""User-global pre-keyring token location.  Read-only back-compat: we
still read it so existing installs keep working, but we no longer
write to it — the user-global file is the source of the dev-vs-demo
clobber bug that keyring_store was built to fix."""

_PER_ENV_TOKEN_FILENAME = ".auth_token"
"""Per-workspace file used when the OS keyring is unavailable.

Stored next to ``users.duckdb`` inside the workspace's
``.olav/databases/`` directory.  Distinct workspaces have distinct
paths, so this fallback preserves the cross-env isolation that the
keyring path gets via ``service_name``.  ``chmod 600`` after write."""

_KEYRING_PROBE_TIMEOUT_SECONDS = 1.0
"""Max time the availability probe waits for a response.

On headless Linux systems the SecretService backend tries to reach a
DBus session daemon and *blocks indefinitely* when none is running.
A one-second probe is long enough to catch a sluggish healthy backend
and short enough to keep TUI startup snappy when the backend is dead.
"""

_keyring_usable: bool | None = None
"""Cached result of :func:`_keyring_is_usable`.  ``None`` means
"not yet probed"; once set, the cached boolean is returned for every
subsequent call so we don't pay the probe cost or risk a hang twice."""

_keyring_probe_lock = threading.Lock()
"""Guards :data:`_keyring_usable` so concurrent callers see a
coherent cache state instead of racing their own probes."""


def _keyring_is_usable() -> bool:
    """Return whether the OS keyring backend responds in reasonable time.

    This sidesteps the headless-system hang:
    ``keyring.get_password`` with the default ``SecretService`` backend
    blocks on a missing DBus session, which would freeze the TUI login
    gate indefinitely.

    Resolution order:

    1. ``OLAV_DISABLE_KEYRING`` env var set to ``1``/``true``/``yes``
       → force-disable; useful on CI or when the user explicitly wants
       the legacy file path.
    2. ``keyring`` not importable → unavailable.
    3. A synchronous probe ``keyring.get_password(...)`` on a dummy
       service, run in a daemon thread with
       :data:`_KEYRING_PROBE_TIMEOUT_SECONDS` seconds to return.  An
       exception counts as "backend responded" (credentials simply
       missing); no-response counts as unusable.

    Result is cached for the lifetime of the process.
    """
    global _keyring_usable
    with _keyring_probe_lock:
        if _keyring_usable is not None:
            return _keyring_usable

        if os.environ.get("OLAV_DISABLE_KEYRING", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            logger.debug("keyring disabled via OLAV_DISABLE_KEYRING env var")
            _keyring_usable = False
            return False

        try:
            import keyring  # noqa: PLC0415
        except ImportError:
            logger.debug("keyring package not importable")
            _keyring_usable = False
            return False

        probe_result: dict[str, bool] = {}

        def _probe() -> None:
            try:
                keyring.get_password(f"{_DEFAULT_SERVICE_PREFIX}:probe", "")
            except Exception:  # noqa: BLE001
                # Any raised error means the backend was reachable
                # enough to reply, even if with "no such entry".
                pass
            probe_result["ok"] = True

        t = threading.Thread(target=_probe, daemon=True, name="olav-keyring-probe")
        t.start()
        t.join(timeout=_KEYRING_PROBE_TIMEOUT_SECONDS)

        responded = probe_result.get("ok", False)
        if not responded:
            logger.warning(
                "keyring backend did not respond within %ss — treating as "
                "unavailable. Set OLAV_DISABLE_KEYRING=1 to silence this "
                "check, or start a keyring daemon (e.g. gnome-keyring-daemon).",
                _KEYRING_PROBE_TIMEOUT_SECONDS,
            )
        _keyring_usable = responded
        return _keyring_usable


def _reset_keyring_probe_cache() -> None:
    """Clear the probe cache.  Exposed for tests."""
    global _keyring_usable
    with _keyring_probe_lock:
        _keyring_usable = None


def _resolve_users_db(users_db_path: Path | str | None = None) -> Path:
    """Return an absolute ``users.duckdb`` path used for service-name keying.

    Args:
        users_db_path: Explicit override; when ``None``, the path is
            derived from the current workspace via
            :data:`olav.core.config.DATABASES_DIR`.

    Returns:
        Absolute, symlink-resolved path.  Non-existent paths are still
        returned — service-name derivation must be stable even before
        the DB file is created.
    """
    if users_db_path is None:
        from olav.core.config import DATABASES_DIR

        users_db_path = Path(DATABASES_DIR) / "users.duckdb"
    return Path(users_db_path).expanduser().resolve()


def service_name(users_db_path: Path | str | None = None) -> str:
    """Return the keyring service name for a workspace.

    The service name is a stable hash of the ``users.duckdb`` absolute
    path so distinct workspaces never share a keyring slot.

    Args:
        users_db_path: Optional override; defaults to the current
            workspace's ``.olav/databases/users.duckdb``.

    Returns:
        A string of the form ``"olav:<12-hex-digest>"``.
    """
    digest = hashlib.sha256(
        str(_resolve_users_db(users_db_path)).encode("utf-8")
    ).hexdigest()[:12]
    return f"{_DEFAULT_SERVICE_PREFIX}:{digest}"


def _default_username() -> str:
    """Return a sane keyring-account name for the current process."""
    return (os.environ.get("USER") or os.environ.get("USERNAME") or "default").strip()


def save_token(
    token: str,
    *,
    users_db_path: Path | str | None = None,
    username: str | None = None,
    write_file_fallback: bool = True,
) -> str:
    """Persist *token* to the keyring, falling back to the legacy file.

    Args:
        token: The raw bearer token (``olav_<hex>``) returned from
            ``admin add-user`` / ``admin rotate-token`` / ``olav init``.
        users_db_path: Overrides the service-name derivation; production
            callers should leave this ``None``.
        username: Keyring account name; defaults to ``$USER``.
        write_file_fallback: When ``True`` (default), a keyring failure
            writes the token to ``~/.olav/token`` (chmod 600).  Set
            ``False`` in tests that want the failure to bubble up.

    Returns:
        ``"keyring"`` when stored in the OS keyring; ``"file"`` when the
        fallback path was taken.
    """
    service = service_name(users_db_path)
    username = username or _default_username()

    if not _keyring_is_usable():
        if not write_file_fallback:
            raise RuntimeError("keyring backend is unavailable on this system")
        _write_per_env_file(token, users_db_path)
        return "file"

    try:
        import keyring  # noqa: PLC0415  # optional dep; import lazily

        keyring.set_password(service, username, token)
        # Tidy both file locations — keeping any copy in sync with the
        # keyring is a foot-gun.
        _unlink_legacy_file()
        _unlink_per_env_file(users_db_path)
        return "keyring"
    except Exception as exc:  # noqa: BLE001  # keyring raises many concrete types
        logger.warning(
            "keyring save failed (%s: %s); falling back to per-env token file",
            type(exc).__name__,
            exc,
        )
        if not write_file_fallback:
            raise
        _write_per_env_file(token, users_db_path)
        return "file"


def load_token(
    *,
    users_db_path: Path | str | None = None,
    username: str | None = None,
) -> str | None:
    """Return the bearer token for this workspace, if any.

    Resolution order:

    1. ``OLAV_TOKEN`` environment variable.
    2. OS keyring lookup under ``(service_name, username)``.
    3. Legacy ``~/.olav/token`` file.
    4. ``None``.

    Failures in the keyring path are logged at ``DEBUG`` and silently
    fall through — an absent daemon should never turn into a crash.
    """
    env_token = (os.environ.get("OLAV_TOKEN") or "").strip()
    if env_token:
        return env_token

    # Per-env file sits next to users.duckdb and is preferred over the
    # global legacy file whenever it exists — so dev and demo envs read
    # their own tokens even without a keyring.
    per_env = _read_per_env_file(users_db_path)
    if per_env:
        return per_env

    if not _keyring_is_usable():
        return _read_legacy_file()

    service = service_name(users_db_path)
    username = username or _default_username()
    try:
        import keyring  # noqa: PLC0415

        token = keyring.get_password(service, username)
        if token:
            return token.strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("keyring lookup failed: %s", exc)

    return _read_legacy_file()


def clear_token(
    *,
    users_db_path: Path | str | None = None,
    username: str | None = None,
    remove_file: bool = True,
) -> None:
    """Remove any stored token for this workspace.

    Intended for ``admin revoke-token`` and test teardown.  Silently
    ignores ``Not Found`` errors.

    Args:
        users_db_path: Overrides the service-name derivation.
        username: Keyring account name.
        remove_file: When ``True`` (default), also unlink
            ``~/.olav/token`` so a stale legacy file cannot shadow the
            revocation.
    """
    service = service_name(users_db_path)
    username = username or _default_username()

    if _keyring_is_usable():
        try:
            import keyring  # noqa: PLC0415
            import keyring.errors  # noqa: PLC0415

            try:
                keyring.delete_password(service, username)
            except keyring.errors.PasswordDeleteError:
                pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("keyring delete failed: %s", exc)

    if remove_file:
        _unlink_per_env_file(users_db_path)
        _unlink_legacy_file()


def storage_backend_description() -> str:
    """Short human-readable string identifying the active keyring backend.

    Used by ``olav init`` and ``admin rotate-token`` to tell the user
    *where* their token was actually stored (keyring vs legacy file),
    so surprising disk-writes on headless systems are visible.

    Returns ``"unavailable"`` when :func:`_keyring_is_usable` reports
    the backend as dead (or disabled via env var) so the message
    matches actual behaviour.
    """
    if not _keyring_is_usable():
        return "unavailable"
    try:
        import keyring  # noqa: PLC0415

        backend = keyring.get_keyring()
        name = backend.__class__.__name__
        module = getattr(backend.__class__, "__module__", "")
        return f"{module}.{name}" if module else name
    except Exception:  # noqa: BLE001
        return "unavailable"


# ---------------------------------------------------------------------------
# Per-env file helpers (keyring-unavailable fallback)
# ---------------------------------------------------------------------------


def _per_env_token_path(users_db_path: Path | str | None = None) -> Path:
    """Return the per-workspace token file location.

    Stored alongside ``users.duckdb`` so each workspace has its own
    slot.  Creating the directory is deferred to
    :func:`_write_per_env_file`.
    """
    return _resolve_users_db(users_db_path).parent / _PER_ENV_TOKEN_FILENAME


def _write_per_env_file(
    token: str, users_db_path: Path | str | None = None
) -> Path:
    path = _per_env_token_path(users_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        logger.debug("chmod 600 on %s failed", path)
    return path


def _read_per_env_file(users_db_path: Path | str | None = None) -> str | None:
    path = _per_env_token_path(users_db_path)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.debug("per-env token read failed (%s): %s", path, exc)
        return None
    return raw or None


def _unlink_per_env_file(users_db_path: Path | str | None = None) -> None:
    path = _per_env_token_path(users_db_path)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.debug("per-env token unlink failed: %s", exc)


# ---------------------------------------------------------------------------
# Legacy file helpers (read-only back-compat)
# ---------------------------------------------------------------------------


def _read_legacy_file() -> str | None:
    if not _LEGACY_TOKEN_PATH.exists():
        return None
    try:
        raw = _LEGACY_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.debug("legacy token read failed: %s", exc)
        return None
    return raw or None


def _unlink_legacy_file() -> None:
    try:
        _LEGACY_TOKEN_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.debug("legacy token unlink failed: %s", exc)


__all__ = [
    "clear_token",
    "load_token",
    "save_token",
    "service_name",
    "storage_backend_description",
]
