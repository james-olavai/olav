"""Device identity contract and inventory provider.

Provides a unified entry point for resolving device names, aliases, and
management IPs to a canonical ``DeviceIdentity``.  This closes two gaps
from the architecture review:

*   **GAP-01** — InventoryProvider abstraction not yet landed.
*   **GAP-08** — device identity contract has no unified entry point.

The ``InventoryProvider`` protocol is consumed by topology_engine,
query_runner, and other modules that need to normalise ad-hoc device
names (LLDP/CDP neighbor strings, FQDN variants, etc.) to canonical
inventory records.

Hostname normalisation
~~~~~~~~~~~~~~~~~~~~~~
The ``StaticInventoryProvider`` replicates the logic previously done
ad-hoc inside ``topology_engine._normalize_device_name()``:

1. Strip leading/trailing whitespace.
2. Case-insensitive comparison.
3. Strip domain suffix — ``router1.lab.local`` → ``router1``.
4. Match against known canonical names, aliases, and management IPs.

Design reference: dev_docs/07 §GAP-01, §GAP-08
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Canonical identity record for a single network device.

    Attributes
    ----------
    canonical_name:
        The authoritative device name stored in the ``devices`` table.
    aliases:
        Additional name variants (FQDN, short-name, LLDP/CDP neighbor
        strings) that should resolve to this device.
    mgmt_ip:
        Management IP address, if known.
    platform:
        Device platform / NOS identifier (e.g. ``"ios"``, ``"eos"``),
        if known.
    """

    canonical_name: str
    aliases: list[str] = field(default_factory=lambda: list[str]())
    mgmt_ip: str | None = None
    platform: str | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class InventoryProvider(Protocol):
    """Runtime-checkable protocol for device identity resolution.

    Implementations read from whatever backing store they prefer (DuckDB,
    static YAML, an external CMDB API, …).  Consumers only depend on this
    protocol — never on a concrete class.
    """

    def resolve(self, name: str) -> DeviceIdentity | None:
        """Resolve any alias, hostname, FQDN, or IP to a canonical identity.

        Parameters
        ----------
        name:
            Raw device reference.  May be a canonical name, an FQDN
            (``router1.lab.local``), a short name (``Router1``), or a
            management IP.

        Returns
        -------
        DeviceIdentity | None
            The matching identity, or ``None`` if no match is found.
        """
        ...

    def list_devices(self) -> list[DeviceIdentity]:
        """Return all known device identities.

        Returns
        -------
        list[DeviceIdentity]
            Every device in the inventory.
        """
        ...


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _strip_domain(name: str) -> str:
    """Strip the domain suffix from *name*.

    ``router1.lab.local`` → ``router1``
    ``sw-core`` → ``sw-core``  (no-op if no dot present)
    """
    return name.split(".")[0]


def _normalise_key(name: str) -> str:
    """Produce a lowercase, domain-stripped lookup key.

    This is the single canonical normalisation used for all identity
    matching — equivalent to the ad-hoc logic that lived in
    ``topology_engine._normalize_device_name()``.
    """
    stripped = name.strip()
    if not stripped:
        return ""
    return _strip_domain(stripped).lower()


# ---------------------------------------------------------------------------
# Static (DuckDB-backed) implementation
# ---------------------------------------------------------------------------


class StaticInventoryProvider:
    """Inventory provider backed by the DuckDB ``devices`` table.

    On construction the provider reads the ``devices`` table once and
    builds in-memory lookup indices keyed by normalised name, alias, and
    management IP.  Call :pymethod:`refresh` to re-read if the underlying
    table has changed.

    The provider queries both ``hostname`` (netops schema) and ``name``
    (legacy flat schema) columns so that it works regardless of whether the
    v0.12 schema-split migration has been applied.

    Thread-safety is *not* provided — callers in multi-user scenarios
    should create per-request instances or wrap access with a lock.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self._con = con
        self._devices: list[DeviceIdentity] = []
        # Normalised-key → DeviceIdentity
        self._by_name: dict[str, DeviceIdentity] = {}
        # mgmt_ip → DeviceIdentity
        self._by_ip: dict[str, DeviceIdentity] = {}
        self._load()

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> DeviceIdentity | None:
        """Resolve *name* to a canonical ``DeviceIdentity``.

        Resolution order:

        1. Exact normalised-key match (canonical name or alias).
        2. Domain-stripped normalised-key match.
        3. Management IP match.

        Returns ``None`` if no device matches.
        """
        raw = name.strip()
        if not raw:
            return None

        key = _normalise_key(raw)
        if not key:
            return None

        # 1. Direct lookup by normalised canonical name / alias
        hit = self._by_name.get(key)
        if hit is not None:
            return hit

        # 2. Try the original (un-stripped) value as an IP lookup
        hit = self._by_ip.get(raw)
        if hit is not None:
            return hit

        return None

    def list_devices(self) -> list[DeviceIdentity]:
        """Return all loaded device identities."""
        return list(self._devices)

    # ------------------------------------------------------------------
    # Refresh / load
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the ``devices`` table and rebuild lookup indices."""
        self._devices.clear()
        self._by_name.clear()
        self._by_ip.clear()
        self._load()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read the devices table and build identity + index structures."""
        rows = self._fetch_device_rows()
        alias_map = self._fetch_alias_map()

        for canonical_name, mgmt_ip, platform in rows:
            if not canonical_name:
                continue
            name_str = str(canonical_name).strip()
            if not name_str:
                continue

            ip_str = str(mgmt_ip).strip() if mgmt_ip else None
            plat_str = str(platform).strip() if platform else None

            # Build alias list from topology_links neighbor references
            raw_aliases: set[str] = set()
            norm_key = _normalise_key(name_str)
            for alias in alias_map.get(norm_key, set()):
                if _normalise_key(alias) != norm_key:
                    continue  # paranoia guard
                raw_aliases.add(alias)

            # Also add FQDN-style variants of the canonical name
            # (the canonical name itself and its short form if different)
            short = _strip_domain(name_str)
            if short != name_str:
                raw_aliases.add(name_str)  # FQDN is an alias
            elif name_str != short:
                raw_aliases.add(short)

            identity = DeviceIdentity(
                canonical_name=name_str,
                aliases=sorted(raw_aliases),
                mgmt_ip=ip_str if ip_str else None,
                platform=plat_str if plat_str else None,
            )
            self._devices.append(identity)

            # Index: normalised canonical name
            self._by_name[norm_key] = identity

            # Index: normalised aliases
            for alias in raw_aliases:
                akey = _normalise_key(alias)
                if akey and akey not in self._by_name:
                    self._by_name[akey] = identity

            # Index: management IP (exact, not normalised)
            if ip_str:
                self._by_ip[ip_str] = identity

        logger.debug(
            "StaticInventoryProvider loaded %d devices (%d name keys, %d IP keys)",
            len(self._devices),
            len(self._by_name),
            len(self._by_ip),
        )

    def _fetch_device_rows(self) -> list[tuple[str, str | None, str | None]]:
        """Read device rows, handling both legacy and netops schema columns.

        The legacy flat ``devices`` table used ``name`` / ``mgmt_ip`` columns.
        The netops schema uses ``hostname`` / ``ip_address``.  The compat
        view created by the v0.12 migration may expose either shape, so we
        introspect available columns and adapt.
        """
        columns = self._table_columns("devices")
        if not columns:
            logger.warning("devices table not found or empty — inventory will be empty")
            return []

        # Determine the right column names
        name_col = "hostname" if "hostname" in columns else "name"
        ip_col = "ip_address" if "ip_address" in columns else "mgmt_ip"
        plat_col = "platform" if "platform" in columns else None

        select_parts = [name_col, ip_col]
        if plat_col:
            select_parts.append(plat_col)

        sql = f"SELECT {', '.join(select_parts)} FROM devices"  # noqa: S608
        try:
            rows = self._con.execute(sql).fetchall()
        except Exception:
            logger.warning("Failed to query devices table", exc_info=True)
            return []

        # Normalise to 3-tuples (name, ip, platform)
        result: list[tuple[str, str | None, str | None]] = []
        for row in rows:
            name_val = row[0]
            ip_val = row[1] if len(row) > 1 else None
            plat_val = row[2] if len(row) > 2 else None
            result.append((str(name_val) if name_val else "", ip_val, plat_val))
        return result

    def _fetch_alias_map(self) -> dict[str, set[str]]:
        """Derive device aliases from topology_links source/destination names.

        LLDP/CDP neighbors often report FQDNs or case-variant hostnames.
        We collect every unique ``source_device`` and ``destination_device``
        value, normalise it, and group by the normalised key so that
        ``resolve()`` can match these variants.
        """
        alias_map: dict[str, set[str]] = {}

        for col in ("source_device", "destination_device"):
            sql = f"SELECT DISTINCT {col} FROM topology_links"  # noqa: S608
            try:
                rows = self._con.execute(sql).fetchall()
            except Exception:
                # Table may not exist yet
                continue
            for (raw_val,) in rows:
                if not raw_val:
                    continue
                val = str(raw_val).strip()
                if not val:
                    continue
                key = _normalise_key(val)
                if key:
                    alias_map.setdefault(key, set()).add(val)

        return alias_map

    def _table_columns(self, table: str) -> set[str]:
        """Return the set of column names for *table*, or empty set if absent."""
        try:
            info = self._con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ? ",
                [table],
            ).fetchall()
            return {str(row[0]) for row in info}
        except Exception:
            return set()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_inventory_provider(con: duckdb.DuckDBPyConnection) -> InventoryProvider:
    """Create and return the default ``InventoryProvider``.

    Currently returns a ``StaticInventoryProvider`` backed by the given
    DuckDB connection.  Future implementations may layer caching, CMDB
    lookups, or other resolution strategies.

    Parameters
    ----------
    con:
        An open DuckDB connection that has access to the ``devices`` and
        (optionally) ``topology_links`` tables.

    Returns
    -------
    InventoryProvider
        A ready-to-use inventory provider.
    """
    return StaticInventoryProvider(con)
