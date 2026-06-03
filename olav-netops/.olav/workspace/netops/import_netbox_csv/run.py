#!/usr/bin/env python3
"""import_netbox_csv — validate (and optionally push) a NetBox-shaped CSV.

Symmetric counterpart to ``netops/export_netbox_csv``.  Reads
``exports/netbox_devices.csv`` (or any path passed in), validates the
shape against the canonical column contract, and produces a per-row
dry-run report — what each row would create / update / skip if we
were really POSTing to NetBox.

dev_docs/71 Ch10b / Ch10c semantics:

* Default: ``--dry-run`` (validate + report, no HTTP).  Safe for CI.
* ``--write`` actually POSTs to a registered NetBox service:
    - resolves endpoint via ``--endpoint`` arg OR
      ``services.yaml.services.netbox.endpoint``
    - resolves token via ``--token`` arg OR
      ``$NETBOX_TOKEN`` env var (services.yaml's ``token_env`` field)
    - for each CSV row: idempotent lookup-or-create of
      site / manufacturer / device_type / device_role; then POST
      device with the resolved FKs.  Re-running the same CSV
      is a no-op on existing rows.

Validations (dry-run):

1. CSV opens, has the 11 expected columns in the expected order
2. No required-field is empty (name / site / device_role /
   manufacturer / device_type / primary_ip4)
3. ``primary_ip4`` parses as IPv4 (allows blank — interfaceless devs)
4. ``status`` is one of NetBox's allowed device statuses (active /
   planned / staged / failed / inventory / decommissioning / offline)
5. ``snapshot_id`` non-empty (provenance watermark)
6. ``exported_at`` parses as ISO-8601

Output: a Markdown report under
``exports/reports/netbox_import_dry_run.md`` listing each row's verdict
+ a top-line summary.

Usage::

    /import_netbox_csv                                # default file
    /import_netbox_csv --csv exports/my.csv
    /import_netbox_csv --report exports/reports/foo.md
    /import_netbox_csv --write                        # NotImplemented
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import IPv4Address
from pathlib import Path


EXPECTED_COLUMNS = (
    "name", "device_role", "manufacturer", "device_type", "primary_ip4",
    "platform", "site", "status", "tenant", "snapshot_id", "exported_at",
)
REQUIRED_NONEMPTY = ("name", "device_role", "manufacturer", "device_type",
                     "site", "status", "snapshot_id", "exported_at")
ALLOWED_STATUSES = frozenset({
    "active", "planned", "staged", "failed",
    "inventory", "decommissioning", "offline",
})


@dataclass
class RowVerdict:
    line_no: int
    name: str
    verdict: str       # "would_create" | "would_update_metadata" | "skip"
    errors: list[str] = field(default_factory=list)


def _validate_row(row: dict, line_no: int) -> RowVerdict:
    errs: list[str] = []
    for col in REQUIRED_NONEMPTY:
        if not (row.get(col) or "").strip():
            errs.append(f"required column '{col}' is empty")

    # IPv4 parse if non-empty
    ip = (row.get("primary_ip4") or "").strip()
    if ip:
        try:
            IPv4Address(ip)
        except ValueError as exc:
            errs.append(f"primary_ip4 '{ip}' is not a valid IPv4: {exc}")

    status = (row.get("status") or "").strip().lower()
    if status and status not in ALLOWED_STATUSES:
        errs.append(
            f"status '{status}' not in NetBox-allowed set "
            f"{sorted(ALLOWED_STATUSES)}"
        )

    exported_at = (row.get("exported_at") or "").strip()
    if exported_at:
        try:
            datetime.fromisoformat(exported_at)
        except ValueError as exc:
            errs.append(f"exported_at '{exported_at}' not ISO-8601: {exc}")

    verdict = "skip" if errs else "would_create"
    return RowVerdict(
        line_no=line_no,
        name=row.get("name", "").strip() or "(unknown)",
        verdict=verdict,
        errors=errs,
    )


def _write_audit_row(
    *,
    workspace_root: Path,
    csv_path: Path,
    endpoint: str,
    n_created: int,
    n_existed: int,
    n_failed: int,
    n_skipped: int,
) -> Path:
    """Drop a kb_audit/<ts>_netbox_push.yaml row for the write call.

    dev_docs/79: every KB-mutating action is git-trackable. Maps to
    the kb_audit/ contract used by ``commit_to_memory`` and
    ``olav kb remove`` — same fields, ``action: netbox_push``.

    The CSV body sha256 is the integrity tie-back to the exact bytes
    that were pushed; future readers can compare against the CSV in
    git history to reconstruct intent.
    """
    import hashlib
    import os
    from datetime import datetime, timezone

    try:
        import yaml as _yaml
    except ImportError:
        return Path("/tmp/kb_audit_skipped_no_yaml.txt")

    audit_dir = workspace_root / "kb_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).astimezone()
    fname = f"{now.strftime('%Y-%m-%dT%H-%M-%S')}_netbox_push.yaml"
    target = audit_dir / fname

    body_sha = (
        hashlib.sha256(csv_path.read_bytes()).hexdigest()
        if csv_path.exists()
        else ""
    )
    row = {
        "action": "netbox_push",
        "csv_path": str(csv_path),
        "csv_body_sha256": body_sha,
        "endpoint": endpoint,
        "actor": os.environ.get("USER", "unknown"),
        "timestamp": now.isoformat(timespec="seconds"),
        "results": {
            "created": n_created,
            "existed": n_existed,
            "failed": n_failed,
            "skipped_validation": n_skipped,
        },
    }
    target.write_text(
        _yaml.safe_dump(row, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return target


# ── NetBox HTTP client (stdlib only — no requests dep) ──────────────

def _slugify(s: str) -> str:
    """NetBox slug: lowercase + dash-separated alnum, used as the
    foreign-key handle for sites / manufacturers / device-types /
    device-roles when creating them via the API."""
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unnamed"


class NetboxClient:
    """Minimal NetBox REST client for the lookup-or-create chain
    needed by /import_netbox_csv --write.  Stdlib urllib only to
    avoid adding a runtime dependency on `requests`."""

    def __init__(self, endpoint: str, token: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token

    def _request(self, method: str, path: str,
                 data: dict | None = None) -> tuple[int, dict | None]:
        url = f"{self.endpoint}{path}"
        body = None
        headers = {
            "Authorization": f"Token {self.token}",
            "Accept": "application/json",
        }
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = resp.read()
                return resp.status, json.loads(payload) if payload else None
        except urllib.error.HTTPError as exc:
            try:
                err_body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                err_body = {"detail": str(exc)}
            return exc.code, err_body

    def lookup_or_create(
        self,
        resource: str,
        lookup_query: dict,
        create_payload: dict,
    ) -> tuple[int | None, str]:
        """GET ?{lookup_query}; if zero hits, POST {create_payload}.
        Returns (id_or_None, status_word).

        status_word ∈ {"exists", "created", "failed:<msg>"} so the
        per-row report can show what actually happened.
        """
        q = "&".join(f"{k}={v}" for k, v in lookup_query.items())
        code, body = self._request("GET", f"/api/dcim/{resource}/?{q}")
        if code == 200 and body and body.get("count", 0) > 0:
            return body["results"][0]["id"], "exists"
        # Create
        code, body = self._request("POST", f"/api/dcim/{resource}/",
                                   data=create_payload)
        if code in (200, 201) and body:
            return body.get("id"), "created"
        return None, f"failed:{code}:{(body or {}).get('detail') or body}"

    def device_lookup_or_create(
        self, name: str, site_id: int, role_id: int,
        device_type_id: int, status: str = "active",
        platform_id: int | None = None,
    ) -> tuple[int | None, str]:
        q = f"name={name}&site_id={site_id}"
        code, body = self._request("GET", f"/api/dcim/devices/?{q}")
        if code == 200 and body and body.get("count", 0) > 0:
            return body["results"][0]["id"], "exists"
        payload: dict = {
            "name": name,
            "site": site_id,
            "role": role_id,
            "device_type": device_type_id,
            "status": status,
        }
        if platform_id is not None:
            payload["platform"] = platform_id
        code, body = self._request("POST", "/api/dcim/devices/", data=payload)
        if code in (200, 201) and body:
            return body.get("id"), "created"
        return None, f"failed:{code}:{(body or {}).get('detail') or body}"


def _resolve_endpoint_and_token(
    explicit_endpoint: str | None,
    explicit_token: str | None,
) -> tuple[str | None, str | None]:
    """Resolution order:
      endpoint: --endpoint > services.yaml.netbox.endpoint > default
      token:    --token    > $NETBOX_TOKEN env var
    services.yaml lookup is best-effort; missing file is OK.
    """
    endpoint = explicit_endpoint
    token = explicit_token or os.environ.get("NETBOX_TOKEN")
    if endpoint is None:
        try:
            import yaml
            services_yaml = Path(".olav/config/services.yaml")
            if services_yaml.exists():
                data = yaml.safe_load(services_yaml.read_text(encoding="utf-8")) or {}
                stanza = (data.get("services") or {}).get("netbox") or {}
                endpoint = stanza.get("endpoint")
        except Exception:
            pass
    return endpoint, token


def _push_row(client: NetboxClient, row: dict) -> tuple[str, list[str]]:
    """Idempotent lookup-or-create chain for one CSV row.

    Returns (verdict, notes) where verdict is "created" / "exists" /
    "failed_chain".  Notes carries per-step diagnostics that land in
    the markdown report.
    """
    notes: list[str] = []
    site = row["site"].strip()
    site_id, st = client.lookup_or_create(
        "sites",
        lookup_query={"name": site},
        create_payload={"name": site, "slug": _slugify(site)},
    )
    notes.append(f"site '{site}': {st}")
    if site_id is None:
        return "failed_chain", notes

    manu = row["manufacturer"].strip()
    manu_id, st = client.lookup_or_create(
        "manufacturers",
        lookup_query={"name": manu},
        create_payload={"name": manu, "slug": _slugify(manu)},
    )
    notes.append(f"manufacturer '{manu}': {st}")
    if manu_id is None:
        return "failed_chain", notes

    dt = row["device_type"].strip()
    dt_id, st = client.lookup_or_create(
        "device-types",
        lookup_query={"model": dt, "manufacturer_id": manu_id},
        create_payload={
            "manufacturer": manu_id,
            "model": dt,
            "slug": _slugify(f"{manu}-{dt}"),
        },
    )
    notes.append(f"device_type '{dt}': {st}")
    if dt_id is None:
        return "failed_chain", notes

    role = row["device_role"].strip()
    role_id, st = client.lookup_or_create(
        "device-roles",
        lookup_query={"name": role},
        create_payload={"name": role, "slug": _slugify(role)},
    )
    notes.append(f"device_role '{role}': {st}")
    if role_id is None:
        return "failed_chain", notes

    # Platform is optional — only resolve if the CSV row carries one.
    # NetBox v4+ treats platform as a separate object referenced by id.
    platform_id: int | None = None
    plat = (row.get("platform") or "").strip()
    if plat:
        plat_id, st = client.lookup_or_create(
            "platforms",
            lookup_query={"name": plat},
            create_payload={"name": plat, "slug": _slugify(plat)},
        )
        notes.append(f"platform '{plat}': {st}")
        if plat_id is None:
            return "failed_chain", notes
        platform_id = plat_id

    dev_id, st = client.device_lookup_or_create(
        name=row["name"].strip(),
        site_id=site_id,
        role_id=role_id,
        device_type_id=dt_id,
        status=row["status"].strip().lower() or "active",
        platform_id=platform_id,
    )
    notes.append(f"device '{row['name']}': {st}")
    if dev_id is None:
        return "failed_chain", notes
    return ("created" if "created" in notes[-1] else "exists"), notes


def _render_report(verdicts: list[RowVerdict], csv_path: Path,
                   col_check: str) -> str:
    n_total = len(verdicts)
    n_skip = sum(1 for v in verdicts if v.verdict == "skip")
    n_ok = n_total - n_skip
    overall = "✅ ALL ROWS VALID" if n_skip == 0 else "❌ VALIDATION FAILURES"

    lines = [
        "# NetBox CSV Dry-Run Import Report",
        "",
        f"**Source CSV**: `{csv_path}`",
        f"**Total rows**: {n_total}",
        f"**Would create**: {n_ok}",
        f"**Skipped (validation errors)**: {n_skip}",
        f"**Verdict**: {overall}",
        "",
        "## Column header check",
        "",
        col_check,
        "",
        "## Per-row verdicts",
        "",
        "| Line | Name | Verdict | Notes |",
        "|---|---|---|---|",
    ]
    for v in verdicts:
        notes = "; ".join(v.errors) if v.errors else "—"
        lines.append(f"| {v.line_no} | {v.name} | {v.verdict} | {notes} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="import_netbox_csv",
        description="Validate + dry-run import a NetBox-shaped CSV.",
    )
    parser.add_argument(
        "--csv", default="exports/netbox_devices.csv",
        help="Source CSV (default: exports/netbox_devices.csv)",
    )
    parser.add_argument(
        "--report", default="exports/reports/netbox_import_dry_run.md",
        help="Output markdown report path",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Actually POST validated rows to NetBox.  Requires --endpoint "
             "(or services.yaml.netbox.endpoint) + --token (or $NETBOX_TOKEN). "
             "Idempotent: re-running on the same CSV is a no-op.",
    )
    parser.add_argument(
        "--endpoint", default=None,
        help="NetBox API endpoint (default: services.yaml.netbox.endpoint)",
    )
    parser.add_argument(
        "--token", default=None,
        help="NetBox API token (default: $NETBOX_TOKEN)",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}", file=sys.stderr)
        print(
            "   Run `olav --agent netops \"/export_netbox_csv\"` first.",
            file=sys.stderr,
        )
        return 1

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("❌ empty CSV (no header row)", file=sys.stderr)
            return 1
        actual_cols = tuple(reader.fieldnames)
        if actual_cols == EXPECTED_COLUMNS:
            col_check = (
                f"✓ Header columns match the canonical contract "
                f"({len(EXPECTED_COLUMNS)} columns, exact order)."
            )
        else:
            missing = [c for c in EXPECTED_COLUMNS if c not in actual_cols]
            extra = [c for c in actual_cols if c not in EXPECTED_COLUMNS]
            order_drift = (
                tuple(c for c in actual_cols if c in EXPECTED_COLUMNS)
                != tuple(c for c in EXPECTED_COLUMNS if c in actual_cols)
            )
            bullets = []
            if missing:
                bullets.append(f"- missing: `{missing}`")
            if extra:
                bullets.append(f"- extra: `{extra}`")
            if order_drift:
                bullets.append("- present columns are out of canonical order")
            col_check = (
                "⚠ Header mismatch vs canonical contract:\n"
                + "\n".join(bullets)
                + f"\n\nExpected: `{list(EXPECTED_COLUMNS)}`\n"
                f"Actual:   `{list(actual_cols)}`"
            )

        verdicts = [
            _validate_row(row, line_no=i + 2)  # +2: 1-indexed + header line
            for i, row in enumerate(reader)
        ]

    # Render the dry-run base report once — both paths reuse it.
    report = _render_report(verdicts, csv_path, col_check)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # ── --write path (Ch10c real POST) ──────────────────────────────
    if args.write:
        endpoint, token = _resolve_endpoint_and_token(args.endpoint, args.token)
        if not endpoint:
            print(
                "❌ --write needs an endpoint (--endpoint or "
                "services.yaml.netbox.endpoint)", file=sys.stderr,
            )
            return 2
        if not token:
            print(
                "❌ --write needs a token (--token or $NETBOX_TOKEN env var)",
                file=sys.stderr,
            )
            return 2

        # Re-read CSV rows for the push (validation already populated verdicts)
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
        client = NetboxClient(endpoint=endpoint, token=token)

        push_lines = [
            "",
            "## Real-write results (--write)",
            "",
            f"**Endpoint**: `{endpoint}`",
            "",
            "| Line | Name | Verdict | Notes |",
            "|---|---|---|---|",
        ]
        n_created = 0
        n_existed = 0
        n_failed = 0
        for v, row in zip(verdicts, rows):
            if v.verdict == "skip":
                push_lines.append(
                    f"| {v.line_no} | {v.name} | skip (validation) | {'; '.join(v.errors)} |"
                )
                continue
            push_verdict, notes = _push_row(client, row)
            note_text = " · ".join(notes)
            push_lines.append(
                f"| {v.line_no} | {v.name} | {push_verdict} | {note_text} |"
            )
            if push_verdict == "created":
                n_created += 1
            elif push_verdict == "exists":
                n_existed += 1
            else:
                n_failed += 1

        push_lines.extend([
            "",
            f"**Created**: {n_created} · **Already existed**: {n_existed} "
            f"· **Failed**: {n_failed}",
        ])

        report_path.write_text(report + "\n" + "\n".join(push_lines), encoding="utf-8")

        # 2026-05-15 (dev_docs/79): every KB-mutating action drops a
        # git-trackable kb_audit/ row.  --write into NetBox is the
        # services-side counterpart of memory-curator commit — same
        # audit principle applies.
        audit_path = _write_audit_row(
            workspace_root=Path(".olav/workspace"),
            csv_path=csv_path,
            endpoint=endpoint,
            n_created=n_created,
            n_existed=n_existed,
            n_failed=n_failed,
            n_skipped=sum(1 for v in verdicts if v.verdict == "skip"),
        )

        print(
            f"✓ real-write done: "
            f"{n_created} created | {n_existed} existed | {n_failed} failed"
        )
        print(f"  endpoint: {endpoint}")
        print(f"  report  : {report_path}")
        print(f"  audit   : {audit_path}")
        return 0 if n_failed == 0 else 1

    report_path.write_text(report, encoding="utf-8")

    n_total = len(verdicts)
    n_skip = sum(1 for v in verdicts if v.verdict == "skip")
    n_ok = n_total - n_skip

    print(f"✓ dry-run complete: {n_total} rows | {n_ok} would create | {n_skip} skipped")
    print(f"  source : {csv_path}")
    print(f"  report : {report_path}")
    if n_skip:
        # Surface first 3 failure rows inline so operators don't have to
        # open the file just to see what's wrong.
        print(f"  first failures:")
        for v in verdicts:
            if v.verdict == "skip":
                print(f"    line {v.line_no} ({v.name}): {'; '.join(v.errors)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
