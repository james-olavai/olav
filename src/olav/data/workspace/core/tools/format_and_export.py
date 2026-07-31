"""Data Export Tool — minimal file exporter.

One unified export entry point with automatic format detection.
Only the orchestrator may call this tool; sub-agents must not write
files directly.

Design:
- No hardcoding: no keyword maps, no format branching by intent.
- Auto-detection: the format is inferred from the data itself.
- Unified output: every file lands under exports/.
- Simple interface: 3 arguments with sensible defaults.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


@tool
def format_and_export(
    data: str,
    filename: str | None = None,
    format: str | None = None,
    subdir: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Save string content to exports/ — supports md/json/csv/yaml/sh/mmd formats.

    ``data`` is the literal file content as a STRING, not a dict or tool result.
    Full usage and anti-patterns: tool_help('format_and_export').

    Args:
        data:     File content as a string. For CSV/JSON pass a JSON-serialised
                  array/object; for md/sh/txt pass the literal text.
        filename: Basename without extension. Auto-generated if omitted.
        format:   md / json / txt / csv / yaml / mmd / sh. Auto-detected if omitted.
        subdir:   Subdir under exports/. Auto-routed by format if omitted.
        mode:     "overwrite" (default) or "append". Append = REPORT MODE
                  incremental writing; text formats only (md/txt/mmd/sh).

    Returns:
        {"path": "exports/.../file.ext", "absolute_path": "...", "size": N, "format": ".."}
    """
    # Normalise mode early; reject malformed values up-front.
    if mode is None:
        mode = "overwrite"
    if isinstance(mode, str):
        mode = mode.strip().lower()
    if mode not in ("overwrite", "append"):
        raise ValueError(f"mode must be 'overwrite' or 'append', got {mode!r}")
    # 1. Determine output directory based on format.
    # WRITER-WRONG-PATH (R82): the previous import was
    # ``from olav.core.config import EXPORTS_DIR as REPORTS_DIR`` and the
    # csv/json branches used ``REPORTS_DIR.parent`` — that's the project
    # root, not exports/.  Fresh-demo verification ended up writing
    # ``devices.csv`` straight to ``~/olav-demo/``.  Fixed: data files
    # land under ``exports/`` directly; narrative reports under
    # ``exports/reports/``.
    from olav.core.config import EXPORTS_DIR

    # R100/S2: strip leading/trailing literal quotes that small models
    # (qwen3.6-27b-dense empirically observed 2026-04-29 demo7 Ch8 v5)
    # bake into short string-typed args via their JSON-construction
    # heuristic.  Behaviour: long fields like ``data`` come through clean
    # as plain strings, but short identifier-like fields (filename,
    # format, subdir) sometimes arrive as ``'"reports"'`` — literal
    # quote characters are part of the value, not the JSON wire format.
    # The ``json.loads`` round-trip in the OpenAI compat path doesn't
    # detect this because ``'"reports"'`` is technically valid JSON for
    # a string with content ``"reports"`` if the outer quotes are
    # interpreted as JSON delimiters; in practice the doubled quoting
    # ends up in the Python string.  Defensive strip protects against
    # both single- and double-quoted leakage.
    def _strip_quote_leak(s: str | None) -> str | None:
        if not isinstance(s, str):
            return s
        s = s.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            s = s[1:-1].strip()
        return s

    filename = _strip_quote_leak(filename)
    format = _strip_quote_leak(format)
    subdir = _strip_quote_leak(subdir)

    # Coerce LLM-serialised "null" / "None" / "" subdir back to Python None
    # — small models often pass these as literal strings via JSON tool args.
    if isinstance(subdir, str) and subdir.strip().lower() in ("", "null", "none"):
        subdir = None

    # Drop a redundant "exports" / "exports/" prefix the agent may have
    # added — ``subdir`` is already relative to EXPORTS_DIR so passing
    # ``subdir="exports"`` produces ``exports/exports/...``.  Strip
    # leading slashes too so ``subdir="/scripts"`` doesn't escape.
    if isinstance(subdir, str):
        cleaned = subdir.strip().lstrip("/")
        # Handle "exports", "exports/", "exports/foo" — collapse leading
        # ``exports/`` and use the remainder; bare "exports" → None.
        if cleaned == EXPORTS_DIR.name:
            subdir = None
        elif cleaned.startswith(EXPORTS_DIR.name + "/"):
            subdir = cleaned[len(EXPORTS_DIR.name) + 1:] or None
        else:
            subdir = cleaned or None

    if subdir is not None:
        # Explicit subdir overrides all automatic routing.
        # subdir is relative to EXPORTS_DIR (e.g. "scripts" → exports/scripts/)
        output_dir = EXPORTS_DIR / subdir
    elif format and format.lower() in ("csv", "json", "yaml", "yml"):
        output_dir = EXPORTS_DIR  # exports/<file>.csv
    elif format and format.lower() in ("md", "txt", "mmd"):
        output_dir = EXPORTS_DIR / "reports"  # exports/reports/<file>.md
    elif format and format.lower() in ("drawio", "puml"):
        # Topology / diagram artefacts get their own subdir so reports/
        # stays text-only and downstream consumers (Confluence sync,
        # ``olav diagram-bundle``, etc.) can glob ``exports/topology/*``.
        output_dir = EXPORTS_DIR / "topology"  # exports/topology/<file>.drawio
    else:
        output_dir = None  # resolved after format detection

    # 2. Parse JSON strings into native Python objects.
    #    LLM tool calls often pass query_database results as JSON-encoded
    #    strings (the only legit way to pass list[dict] through OpenAI's
    #    string-typed `arguments` field).  Converting early ensures
    #    _detect_format and _write_csv see list[dict].
    #
    #    R100/S2 (2026-04-29): the legacy dict-extraction block (which
    #    handled {"content": "..."} and {"# title": "md"}) was removed
    #    because the strict ``data: str`` Pydantic schema now rejects
    #    dicts before this function runs.  If the LLM passes a dict
    #    arg, it gets a Pydantic ValidationError with the schema spec
    #    in the error message — that is the desired feedback signal.
    if isinstance(data, str):
        stripped = data.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, (list, dict)):
                    data = parsed
            except (json.JSONDecodeError, ValueError):
                pass

    # 4. Auto-detect format (if not specified)
    if not format:
        format = _detect_format(data)

    # 4. Resolve output_dir if not yet determined (only when subdir=None and format was auto-detected)
    if output_dir is None:
        if format in ("csv", "json", "yaml", "yml", "sh"):
            output_dir = EXPORTS_DIR  # exports/<file>.csv
        elif format in ("drawio", "puml"):
            output_dir = EXPORTS_DIR / "topology"  # exports/topology/<file>.drawio
        else:
            output_dir = EXPORTS_DIR / "reports"  # exports/reports/<file>.md

    output_dir.mkdir(parents=True, exist_ok=True)

    # Coerce LLM-serialised "null" / "None" filename to Python None too.
    if isinstance(filename, str) and filename.strip().lower() in ("", "null", "none"):
        filename = None

    # 5. Auto-generate filename (if not specified)
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{timestamp}"

    # 6. Sanitize filename and handle existing extension
    #    If filename has extension, we use it as the format if format was auto-detected
    from pathlib import PurePath
    p = PurePath(filename)
    if p.suffix and p.suffix[1:].lower() in ("md", "json", "txt", "csv", "yaml", "yml", "mmd", "sh"):
        # If user provided extension, and it's a known one, split it
        actual_format = p.suffix[1:].lower()
        filename = p.stem
        # If format was auto-detected, override with filename's extension
        # If format was explicitly passed, verify they match or override?
        # Here we let explicit 'format' arg win if provided, otherwise filename's ext wins.
        if not format or format == "md": # md is a common fallback
             format = actual_format
    else:
        filename = p.name

    if ".." in filename or filename.startswith("/"):
        raise ValueError(f"Invalid filename: {filename}. Cannot contain '..' or start with '/'")

    # 7. Build full path
    filepath = output_dir / f"{filename}.{format}"

    # Reject append for structured formats — byte concatenation would
    # corrupt JSON/CSV/YAML parse.
    if mode == "append" and format in ("json", "csv", "yaml", "yml"):
        raise ValueError(
            f"append mode is not supported for {format!r} (would corrupt the parse); "
            f"use mode='overwrite' or write to a different filename"
        )

    # 7. Write file based on format
    _write_file(filepath, data, format, mode=mode)

    # 8. Return result with relative path for display
    return {
        "path": str(filepath.relative_to(Path.cwd())),  # relative, e.g. exports/reports/xxx.csv
        "absolute_path": str(filepath.absolute()),
        "size": filepath.stat().st_size,
        "format": format,
    }


def _detect_format(data: Any) -> str:  # noqa: ANN401
    """
    Detect the output format from the data itself.

    Rules:
    - starts with # or contains ## → Markdown
    - starts with { or [         → JSON
    - dict/list instance         → JSON
    - any other string           → Text

    Args:
        data: the payload to inspect

    Returns:
        str: detected format (md/json/txt)
    """
    if isinstance(data, str):
        # Markdown markers
        if data.strip().startswith("#") or "\n##" in data or "\n###" in data:
            return "md"

        # CSV markers (comma-separated with consistent column count)
        lines = data.strip().splitlines()
        if len(lines) >= 2:
            first_commas = lines[0].count(",")
            if first_commas >= 1 and all(
                line.count(",") == first_commas for line in lines[:5] if line.strip()
            ):
                return "csv"

        # JSON string
        stripped = data.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                json.loads(data)
                return "json"
            except (json.JSONDecodeError, ValueError):
                pass


        # Mermaid markers (a graph/flowchart keyword or a mermaid code fence)
        if "graph " in data.lower() or "flowchart " in data.lower() or "```mermaid" in data.lower():
            # Content starting with # is titled Markdown that happens to embed a
            # diagram — keep .md. Only a bare diagram is treated as .mmd.
            if not (data.strip().startswith("#") or "\n##" in data):
                return "mmd"

        # Fall back to plain text
        return "txt"

    elif isinstance(data, (dict, list)):
        # Python containers serialise as JSON
        return "json"

    else:
        # Anything else is stringified
        return "txt"


def _write_file(filepath: Path, data: Any, format: str, mode: str = "overwrite") -> None:  # noqa: ANN401
    """
    Write the payload to disk according to *format*.

    Args:
        filepath: destination path
        data:     payload to write
        format:   file format
        mode:   'overwrite' (default) or 'append' — append only valid for text formats
    """
    if format == "json":
        # JSON: structured output (mode='append' rejected earlier in format_and_export)
        if isinstance(data, (dict, list)):
            content = json.dumps(data, indent=2, ensure_ascii=False)
        elif isinstance(data, str):
            # Already a JSON string — reformat it
            try:
                obj = json.loads(data)
                content = json.dumps(obj, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                content = data
        else:
            content = json.dumps(str(data), indent=2, ensure_ascii=False)

        filepath.write_text(content, encoding="utf-8")

    elif format == "csv":
        # CSV: delegated to pandas (mode='append' rejected earlier)
        _write_csv(filepath, data)

    elif format == "yaml":
        # YAML: structured data (mode='append' rejected earlier)
        _write_yaml(filepath, data)

    elif format == "sh":
        # Shell script: write as plain text, ensure LF line endings
        content = str(data)
        if mode == "append":
            with open(filepath, "a", encoding="utf-8", newline="\n") as f:
                f.write(content)
        else:
            filepath.write_text(content, encoding="utf-8", newline="\n")

    else:
        # Markdown / text / anything else
        if format == "md" and isinstance(data, dict):
            content = _dict_to_markdown(data)
        else:
            content = str(data)
        if mode == "append":
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            filepath.write_text(content, encoding="utf-8")


def _dict_to_markdown(data: dict[str, Any], level: int = 1) -> str:
    """Recursively convert a dictionary to Markdown headers and lists."""
    lines = []
    for key, val in data.items():
        # Title case the key for headers
        title = str(key).replace("_", " ").title()

        if isinstance(val, dict):
            lines.append(f"{'#' * level} {title}")
            lines.append(_dict_to_markdown(val, level + 1))
        elif isinstance(val, list):
            lines.append(f"{'#' * level} {title}")
            for item in val:
                if isinstance(item, dict):
                    # For list of dicts, try to make a table or just nested list
                    lines.append(_dict_to_markdown(item, level + 1))
                else:
                    lines.append(f"- {item}")
        else:
            if level == 1:
                lines.append(f"# {val}" if key == "title" else f"**{title}**: {val}")
            else:
                lines.append(f"- **{title}**: {val}")
        lines.append("")
    return "\n".join(lines)


def _write_csv(filepath: Path, data: Any) -> None:  # noqa: ANN401
    """
    Write CSV file.

    Handles:
    - list[dict] → proper multi-column CSV via pandas/csv
    - JSON string → parse first, then treat as list[dict]
    - dict → single-row CSV
    - Other → fallback to single-column

    Args:
        filepath: File path
        data: Data to write (ideally list[dict] or JSON string of same)
    """
    # Parse JSON strings into native Python objects first
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, (list, dict)):
                data = parsed
        except (json.JSONDecodeError, ValueError):
            pass

    try:
        import pandas as pd

        if isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict):
                df = pd.DataFrame(data)
            else:
                df = pd.DataFrame(data, columns=["value"])
        elif isinstance(data, dict):
            df = pd.DataFrame([data])
        else:
            # Last resort: coerce to string in a single column
            df = pd.DataFrame([{"data": str(data)}])

        df.to_csv(filepath, index=False, encoding="utf-8")

    except ImportError:
        import csv

        with open(filepath, "w", encoding="utf-8", newline="") as f:
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                # Collect ALL unique keys from ALL dicts, not just the first one
                # This handles cases where dicts have different field sets
                all_keys: set[str] = set()
                for row in data:
                    if isinstance(row, dict):
                        all_keys.update(row.keys())
                fieldnames = sorted(all_keys)

                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(data)
            elif isinstance(data, dict):
                writer = csv.DictWriter(f, fieldnames=data.keys())
                writer.writeheader()
                writer.writerow(data)
            else:
                f.write(str(data))


def _write_yaml(filepath: Path, data: Any) -> None:  # noqa: ANN401
    """
    Write the payload as YAML.

    Args:
        filepath: destination path
        data:     payload to write
    """
    try:
        import yaml

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    except ImportError:
        # yaml not installed — fall back to JSON
        content = json.dumps(data, indent=2, ensure_ascii=False)
        filepath.write_text(content, encoding="utf-8")


# ============================================================================
# Self-test
# ============================================================================

if __name__ == "__main__":
    """Smoke-test the export tool."""

    print("=" * 80)
    print("Testing the format_and_export tool")
    print("=" * 80)

    # 1: Markdown report
    print("\n1️⃣ Markdown report")
    md_content = """# Network diagnostic report

## Symptom
R1's OSPF neighbor is down

## Root cause
Subnet mask mismatch

## Recommended fix
Correct the interface IP configuration
"""
    result = format_and_export(md_content, filename="test_diagnosis")
    print(f"✅ exported: {result['path']} ({result['size']} bytes)")

    # 2: JSON data
    print("\n2️⃣ JSON data")
    json_data = {
        "devices": [
            {"hostname": "R1", "ip": "192.168.1.1"},
            {"hostname": "R2", "ip": "192.168.1.2"},
        ]
    }
    result = format_and_export(json_data, filename="test_devices")
    print(f"✅ exported: {result['path']} ({result['size']} bytes)")

    # 3: plain text
    print("\n3️⃣ Plain text")
    text_content = "R1#show tech-support\nCisco IOS Software...\n"
    result = format_and_export(text_content, filename="test_tech_support")
    print(f"✅ exported: {result['path']} ({result['size']} bytes)")

    # 4: CSV data
    print("\n4️⃣ CSV export")
    csv_data = [
        {"vlan_id": 10, "name": "Management", "status": "active"},
        {"vlan_id": 20, "name": "Data", "status": "active"},
        {"vlan_id": 30, "name": "Voice", "status": "inactive"},
    ]
    result = format_and_export(csv_data, filename="test_vlans", format="csv")
    print(f"✅ exported: {result['path']} ({result['size']} bytes)")

    # 5: auto-detection
    print("\n5️⃣ Automatic format detection")
    auto_data = "## Auto-detection test\nThis should be recognised as Markdown"
    result = format_and_export(auto_data)  # no filename, no format
    print(f"✅ auto-detected and exported: {result['path']} (format: {result['format']})")

    print("\n" + "=" * 80)
    print("✅ All checks passed — see the exports/ directory for the files")
    print("=" * 80)
