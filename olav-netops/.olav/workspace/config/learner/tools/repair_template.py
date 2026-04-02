#!/usr/bin/env python3
"""
Tool: repair_template — Zero-Touch Template Auto-Repair

Single atomic tool for Stage 5 self-healing in the snapshot pipeline.
Given a (device, command) pair with empty parsed_data, it:
  1. Reads raw SSH output from latest snapshot on disk.
  2. Looks up device platform from DuckDB.
  3. Uses LLM (ReAct + reflection loop) to generate a working TextFSM template.
  4. Saves template to .olav/templates/ (unified single directory).
  5. Calls reparse_outputs() to validate records > 0.

Designed to be called directly from the onboard pipeline without any user
interaction — no approved_fields, no ntc_references lookup required.

Usage (standalone CLI):
    python repair_template.py --device R1 --command "show ip route"
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """Locate project root by walking up to find .olav/."""
    start = Path(__file__).resolve()
    for parent in [start, *start.parents]:
        if (parent / ".olav").is_dir():
            return parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
SNAPSHOTS_DIR = PROJECT_ROOT / "exports" / "snapshots"

# Derive from config SSOT — never hardcode paths (see copilot-instructions §3 ANTI-PATTERNS)
from olav.core.config import TEXTFSM_TEMPLATES_DIR

CUSTOM_TEMPLATES_DIR = Path(TEXTFSM_TEMPLATES_DIR)


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _find_raw_file(device: str, command: str) -> Path | None:
    """Return the most recent raw output file for device/command (no SSH)."""
    cmd_slug = command.lower().replace(" ", "_") + ".txt"

    # Prefer 'latest' symlink
    via_latest = SNAPSHOTS_DIR / "latest" / "raw" / device / cmd_slug
    if via_latest.exists():
        return via_latest

    # Fall back to newest dated snapshot directory
    try:
        dated = sorted(
            [d for d in SNAPSHOTS_DIR.iterdir()
             if d.is_dir() and d.name not in ("latest", "json")],
            reverse=True,
        )
        for snap_dir in dated:
            candidate = snap_dir / "raw" / device / cmd_slug
            if candidate.exists():
                return candidate
    except Exception:
        pass
    return None


def _get_platform(device: str) -> str:
    """Fetch device platform from DuckDB."""
    try:
        from olav.core.database import get_database
        row = get_database().conn.execute(
            "SELECT platform FROM devices WHERE name = ?", [device]
        ).fetchone()
        return row[0] if row else ""
    except Exception:
        return ""


def _llm_generate(platform: str, command: str, raw_output: str) -> str | None:
    """ReAct loop: generate TextFSM template, test, reflect, retry up to 3×."""
    import textfsm
    from langchain_openai import ChatOpenAI

    from olav.core.config import settings

    llm = ChatOpenAI(
        model=settings.llm_model_name,
        temperature=0.15,
        timeout=120,
        api_key=settings.llm_api_key or None,
        base_url=settings.llm_base_url or None,
    )

    # Check if a NTC reference template exists for context
    ntc_context = ""
    try:
        from ntc_templates.get_template import get_template
        ref = get_template(platform=platform, command=command, netmiko=False)
        if ref:
            ntc_context = f"\n**NTC reference template** (use as pattern inspiration):\n```\n{ref[:800]}\n```\n"
    except Exception:
        pass

    prompt = (
        f"You are a TextFSM expert.\n\n"
        f"Platform: `{platform}`\nCommand: `{command}`\n"
        f"{ntc_context}"
        f"\n**Raw CLI output** (first 4 000 chars):\n```\n{raw_output[:4000]}\n```\n\n"
        "Write a TextFSM template that extracts ALL data rows from this output. "
        "Return ONLY the complete template code — no markdown fences, no explanations."
    )

    for attempt in range(1, 4):
        response = llm.invoke([{"role": "user", "content": prompt}])
        content = response.content.strip()
        # Strip any accidental markdown fences
        content = re.sub(r"^```[a-z]*\n?|```$", "", content, flags=re.MULTILINE).strip()

        try:
            fsm = textfsm.TextFSM(io.StringIO(content))
            rows = fsm.ParseText(raw_output)
            if rows:
                logger.info("Template accepted on attempt %d (%d records)", attempt, len(rows))
                return content
            # Syntax OK but 0 records — reflect
            prompt += (
                f"\n\nAttempt {attempt}: valid syntax but 0 records parsed.\n"
                f"Headers defined: {fsm.header}\n"
                f"First 30 raw lines:\n{chr(10).join(raw_output.splitlines()[:30])}\n\n"
                "Fix the regex so every data line is captured. Return ONLY the corrected template."
            )
        except Exception as exc:
            prompt += f"\n\nAttempt {attempt} — syntax error: {exc}. Fix and retry."

    return None  # All attempts failed


def _save(platform: str, command: str, content: str) -> Path:
    """Persist template to .olav/templates/ (unified single directory)."""
    CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    filename = platform + "_" + command.lower().replace(" ", "_") + ".textfsm"
    path = CUSTOM_TEMPLATES_DIR / filename
    path.write_text(content, encoding="utf-8")
    logger.info("Saved template: %s", path)
    return path


def _reparse(device: str, command: str, platform: str = "") -> dict:
    """Call reparse_outputs to update DB with new template.

    When ``platform`` is provided, batches across ALL devices of that platform
    (template repairs are platform-level).  Always validates using ``device``
    so the caller gets a meaningful records count.
    """
    reparse_py = PROJECT_ROOT / ".olav" / "workspace" / "config" / "sync" / "tools" / "reparse_outputs.py"
    if not reparse_py.exists():
        return {"success": False, "error": "reparse_outputs.py not found"}
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("reparse_outputs", reparse_py)
    mod = module_from_spec(spec)
    if str(reparse_py.parent) not in sys.path:
        sys.path.insert(0, str(reparse_py.parent))
    spec.loader.exec_module(mod)
    fn = mod.reparse_outputs
    call = fn.func if hasattr(fn, "func") else fn
    if platform:
        # Batch: reparse all devices of this platform
        batch = call(platform=platform, command=command)
        # For validation: report the sample device's record count specifically
        sample = call(device=device, command=command)
        return {
            "success": batch.get("success", False),
            "records": sample.get("records", 0),
            "devices_updated": batch.get("devices_updated", []),
            "errors": batch.get("errors"),
        }
    return call(device=device, command=command)


# ──────────────────────────────────────────────────────────────────────────────
# Public @tool
# ──────────────────────────────────────────────────────────────────────────────

@tool
def repair_template(device: str, command: str) -> dict:
    """Zero-touch auto-repair for a single (device, command) parsing gap.

    Stage 5 of the snapshot pipeline — called when parsed_data is empty after
    Stage 2. No user interaction required.

    Args:
        device:  Device name (must exist in DuckDB devices table).
        command: CLI command string (e.g. "show ip route").

    Returns:
        {
          "success": bool,
          "device": str,
          "command": str,
          "records": int,      # rows parsed after repair (0 on failure)
          "template_path": str | None,
          "error": str | None,
        }
    """
    # 1. Find raw file
    raw_file = _find_raw_file(device, command)
    if not raw_file:
        return {"success": False, "device": device, "command": command,
                "records": 0, "template_path": None,
                "error": f"No raw file found for {device}/{command}"}

    try:
        raw_output = raw_file.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"success": False, "device": device, "command": command,
                "records": 0, "template_path": None, "error": f"Cannot read raw file: {exc}"}

    # 2. Platform
    platform = _get_platform(device)
    if not platform:
        return {"success": False, "device": device, "command": command,
                "records": 0, "template_path": None,
                "error": f"Unknown platform for device '{device}'"}

    # 3. LLM generate
    logger.info("Repairing template for %s/%s (platform=%s)", device, command, platform)
    content = _llm_generate(platform, command, raw_output)
    if not content:
        return {"success": False, "device": device, "command": command,
                "records": 0, "template_path": None,
                "error": "LLM failed to generate a working template after 3 attempts"}

    # 4. Save
    saved_path = _save(platform, command, content)

    # 5. Reparse + validate (batch by platform so all devices benefit)
    result = _reparse(device, command, platform=platform)
    records = result.get("records", 0) if isinstance(result, dict) else 0
    success = records > 0

    return {
        "success": success,
        "device": device,
        "command": command,
        "records": records,
        "template_path": str(saved_path),
        "error": None if success else f"0 records after reparse (reparse result: {result})",
    }


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry-point (for manual use / testing)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Auto-repair TextFSM template for a single device/command")
    parser.add_argument("--device", required=True)
    parser.add_argument("--command", required=True)
    args = parser.parse_args()
    result = repair_template.func(device=args.device, command=args.command)
    print(json.dumps(result, indent=2))
