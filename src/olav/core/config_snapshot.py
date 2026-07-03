"""Last-known-good config snapshot + explicit rollback (dev_docs/99 §3.5).

Deliberately explicit, not automatic: an agent or user calls
``restore_last_known_good()`` when they notice a config change broke
something, rather than the system silently reverting deep inside the hot
``get_chat_model()`` call path on every turn. A silent revert would leave
the user believing their new config is active when it isn't — making
recovery a reported, on-demand action avoids that ambiguity entirely.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone

from olav.core.config import CONFIG_DIR

API_JSON_PATH = CONFIG_DIR / "api.json"
SNAPSHOT_PATH = CONFIG_DIR / "api.json.lastgood"


def snapshot_api_json() -> bool:
    """Copy the current api.json to the last-known-good snapshot slot.

    Call this right before committing a newly-validated config change
    (dev_docs/99 §3.4) — it captures the config that was working a moment
    ago, not the one about to replace it.

    Returns:
        True if a snapshot was taken, False if there was no api.json yet
        (nothing to protect on a true first run).
    """
    if not API_JSON_PATH.exists():
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(API_JSON_PATH, SNAPSHOT_PATH)
    return True


def restore_last_known_good() -> dict:
    """Restore api.json from the last-known-good snapshot, if one exists.

    Explicit, user/agent-triggered recovery — never called automatically
    from the LLM/embedding call path.

    Returns:
        {"restored": bool, "message": str}
    """
    if not SNAPSHOT_PATH.exists():
        return {"restored": False, "message": "No last-known-good snapshot found."}

    snapshot_time = datetime.fromtimestamp(
        SNAPSHOT_PATH.stat().st_mtime, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    shutil.copy2(SNAPSHOT_PATH, API_JSON_PATH)
    return {
        "restored": True,
        "message": f"Restored api.json from the snapshot taken {snapshot_time}.",
    }
