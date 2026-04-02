"""Current datetime tool for OLAV Inspection Pipeline.

Provides accurate system time for report timestamps and filenames.
Prevents LLM from using stale/hallucinated dates.
"""

from datetime import datetime

from langchain_core.tools import tool


@tool
def get_current_datetime() -> dict:
    """Get the current system date and time for report naming and timestamps.

    Always call this before generating a report to get the accurate filename
    timestamp. Do NOT infer the current date from training data or context.

    Returns:
        dict with:
          - iso: ISO 8601 datetime string (e.g. "2026-02-19T14:35:22.123456")
          - filename_ts: Compact form for filenames (e.g. "20260219_143522")
          - date: Date string (e.g. "2026-02-19")
          - time: Time string (e.g. "14:35:22")

    Example usage:
        dt = get_current_datetime()
        report_path = f"exports/agent_outputs/inspection_workflow_{dt['filename_ts']}.md"

    """
    now = datetime.now()
    return {
        "iso": now.isoformat(),
        "filename_ts": now.strftime("%Y%m%d_%H%M%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
    }
