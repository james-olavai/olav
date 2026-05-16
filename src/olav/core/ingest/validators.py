"""Cheap pre-flight bundle validator — no DB touch.

The validator answers "is this bundle internally consistent enough to
feed the landing pipeline?" Errors block ingest; warnings flow through.

Implementation notes:
  * Content sha256 is computed over the per-command file bytes in the
    same byte-stable order used by ``scripts/build_portable_ingest_fixture.py``:
    host name asc, then file name asc, full file contents (header + body).
  * For directory bundles only — ``validate_bundle(zip_path)`` is left
    for a follow-up (the reader supports it but the hash needs to read
    the original on-disk bytes that produced the manifest's hash).

  Use this for ``olav ingest validate <path>`` UX and as a precondition
  inside ``ingest_snapshot()``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import Manifest


@dataclass(slots=True)
class ValidationReport:
    """Outcome of ``validate_bundle``.

    Errors are blocking; warnings flow into the caller for surfacing but
    don't refuse ingest.
    """

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hosts_seen: int = 0
    commands_seen: int = 0
    content_sha256_observed: str | None = None


def _hash_bundle_contents(root: Path) -> tuple[str, int, int]:
    """Recompute sha256 over devices/*/*.txt using the canonical order.

    Returns ``(hex_digest, hosts_seen, commands_seen)``.
    """
    h = hashlib.sha256()
    hosts = 0
    cmds = 0
    devices_dir = root / "devices"
    if not devices_dir.is_dir():
        return h.hexdigest(), 0, 0
    for host_dir in sorted(d for d in devices_dir.iterdir() if d.is_dir()):
        hosts += 1
        for cmd_file in sorted(f for f in host_dir.iterdir() if f.is_file() and f.suffix == ".txt"):
            h.update(cmd_file.read_bytes())
            cmds += 1
    return h.hexdigest(), hosts, cmds


def validate_bundle(path: str | Path) -> ValidationReport:
    """Run pre-flight checks on a directory-backed bundle.

    Returns a ``ValidationReport``.  Does NOT raise — exceptional cases
    surface as ``ok=False`` with structured error strings.
    """
    root = Path(path)
    errors: list[str] = []
    warnings: list[str] = []

    if not root.is_dir():
        return ValidationReport(ok=False, errors=[f"bundle root is not a directory: {root}"])

    # ── manifest.yaml ────────────────────────────────────────────
    manifest_path = root / "manifest.yaml"
    if not manifest_path.is_file():
        return ValidationReport(ok=False, errors=[f"manifest.yaml missing under {root}"])

    try:
        manifest_raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return ValidationReport(ok=False, errors=[f"manifest.yaml unparseable: {exc}"])

    try:
        manifest = Manifest.model_validate(manifest_raw)
    except ValidationError as exc:
        return ValidationReport(
            ok=False,
            errors=[f"manifest.yaml schema invalid: {exc.errors()[0]['msg']}"],
        )

    # ── content sha256 ────────────────────────────────────────────
    observed, hosts_seen, commands_seen = _hash_bundle_contents(root)
    if observed != manifest.content_sha256:
        errors.append(
            f"content sha256 mismatch — manifest={manifest.content_sha256[:16]}…, "
            f"observed={observed[:16]}…"
        )

    # ── host-count cross-check ────────────────────────────────────
    if hosts_seen != manifest.hosts_collected:
        warnings.append(
            f"host count drift — manifest.hosts_collected={manifest.hosts_collected}, "
            f"devices/ has {hosts_seen}"
        )
    if hosts_seen == 0:
        warnings.append("devices/ tree is empty")

    return ValidationReport(
        ok=(not errors),
        errors=errors,
        warnings=warnings,
        hosts_seen=hosts_seen,
        commands_seen=commands_seen,
        content_sha256_observed=observed,
    )
