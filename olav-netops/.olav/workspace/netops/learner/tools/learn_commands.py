"""learn_commands — unified parser-learning entry point (ARCH-30, R71a).

Direct-callable function used by both the batch pipeline
(`netops_init` Stage 3.5) and the interactive slash command
(`/learn_cmd`). Internally uses a ThreadPool to parallelise across
(platform, command) groups and enforces a wall-clock budget.

R71a scope:
  * Skeleton + API + concurrency + budget + failure cache
  * Internally calls existing `auto_learn_failed_parses` and
    `pac_learn_failed_parses` sequentially **within each worker**
    (cascade preserved for correctness — the router that collapses
    the cascade lands in R71b)
  * No changes to `run.py` or `cli/builtin.py` yet — side-by-side
    deployment for validation

R71b will replace the cascade with a single LLM call + DSL marker.
R71c will flip `run.py` Stage 3.5 to this entrypoint and retire the
old public APIs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed, TimeoutError as _FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Bump to invalidate all cached failures + frozen artifacts en masse
LEARNER_CONTRACT_VERSION = 1

DEFAULT_BUDGET_SECONDS = 300
DEFAULT_MAX_WORKERS = 5
DEFAULT_MAX_RETRIES = 2
DEFAULT_FAILURE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


@dataclass
class LearnResult:
    newly_parsed: list[dict[str, Any]] = field(default_factory=list)
    frozen: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "newly_parsed": self.newly_parsed,
            "frozen": self.frozen,
            "failed": self.failed,
            "skipped": self.skipped,
            "elapsed_seconds": self.elapsed_seconds,
        }


# ──────────────────────────────────────────────────────────────────────────
# Failure cache (`.olav/templates/_failed_learn.json`)
# ──────────────────────────────────────────────────────────────────────────

def _templates_dir() -> Path:
    """Resolve `.olav/templates/` under the active OLAV project."""
    try:
        from olav.core.config import get_paths_config
        return Path(get_paths_config().agent_dir) / "templates"
    except Exception:
        return Path.home() / ".olav" / "templates"


def _failure_cache_path() -> Path:
    return _templates_dir() / "_failed_learn.json"


def _samples_hash(samples: list[dict[str, Any]]) -> str:
    """Deterministic hash of a (platform, command) group's samples."""
    payload = sorted((s.get("device", ""), (s.get("raw_output") or "")[:4096]) for s in samples)
    h = hashlib.sha256()
    for dev, raw in payload:
        h.update(dev.encode("utf-8"))
        h.update(b"\0")
        h.update(raw.encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()[:32]


def _load_failure_cache() -> dict[str, dict[str, Any]]:
    path = _failure_cache_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as exc:
        logger.warning("learn_commands: failure cache load failed: %s", exc)
        return {}


def _save_failure_cache(cache: dict[str, dict[str, Any]]) -> None:
    path = _failure_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:
        logger.warning("learn_commands: failure cache save failed: %s", exc)


def _cache_key(platform: str, command: str) -> str:
    return f"{platform}/{command}"


def _is_fresh_failure(
    cache_entry: dict[str, Any],
    samples_hash_now: str,
) -> bool:
    """Return True when the cached failure is still applicable.

    Stale if:
      * contract_version drifted (force global re-learn)
      * samples_hash differs (new data, retry)
      * retry_after_seconds elapsed
    """
    if cache_entry.get("contract_version") != LEARNER_CONTRACT_VERSION:
        return False
    if cache_entry.get("samples_hash") != samples_hash_now:
        return False
    attempted = cache_entry.get("attempted_at")
    ttl = cache_entry.get("retry_after_seconds", DEFAULT_FAILURE_TTL_SECONDS)
    if not isinstance(attempted, str):
        return False
    try:
        t0 = datetime.fromisoformat(attempted.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = (datetime.now(timezone.utc) - t0).total_seconds()
    return age < ttl


# ──────────────────────────────────────────────────────────────────────────
# Learner core — single LLM call per command; LLM picks DSL via marker.
# (R71b replacement for the R70 cascade.)
# ──────────────────────────────────────────────────────────────────────────

def _learn_one_group(
    platform: str,
    command: str,
    samples: list[dict[str, Any]],
    *,
    max_retries: int,
    allow_llm: bool,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Run the learner for a single (platform, command) group.

    Returns ``(status, newly_parsed, freeze_info)``.
    """
    # Import helpers from _lib/ (internal helpers, not exposed @tools).
    import sys as _sys
    from pathlib import Path as _P
    _lib = _P(__file__).resolve().parent.parent / "_lib"
    if str(_lib) not in _sys.path:
        _sys.path.insert(0, str(_lib))

    from analyze_structure import analyze_structure, render_hints  # type: ignore
    from draft_parser import draft_parser  # type: ignore
    from validate_parser import validate_parser  # type: ignore
    from freeze_parser import freeze_parser  # type: ignore

    # Short-circuit: already-frozen parser can parse — run it and return.
    replayed = _try_existing_parser(platform, command, samples)
    if replayed is not None:
        return "learned", replayed, {
            "platform": platform, "command": command,
            "dsl": "existing", "source": "frozen_registry",
        }

    # Fast filter: some outputs aren't worth learning (errors, backup configs).
    first_raw = samples[0].get("raw_output") if samples else ""
    try:
        from olav_netops.core.parse_helpers import should_learn
        if not should_learn(command, first_raw or ""):
            return "failed", [], None
    except Exception:
        pass

    if not allow_llm:
        # Frozen-only mode: no LLM, so we can't draft a new parser.
        return "failed", [], None

    try:
        from olav.core.llm import LLMFactory
        llm = LLMFactory.get_chat_model()
    except Exception as exc:
        logger.info("learn_commands: LLM unavailable: %s", exc)
        return "failed", [], None

    struct = analyze_structure(first_raw or "")
    hints = render_hints(struct)

    prev_code: str | None = None
    prev_error: str | None = None

    for attempt in range(1, max_retries + 1):
        dsl, source = draft_parser(
            llm, platform, command, samples, hints,
            prev_code=prev_code, prev_error=prev_error,
        )
        if not dsl or not source:
            prev_error = "LLM returned empty or unrecognisable response"
            prev_code = source or None
            continue

        v = validate_parser(dsl, source, samples)
        if not v["ok"]:
            prev_code = source
            prev_error = v["diagnostic"]
            logger.debug(
                "learn_commands: %s/%s attempt %d failed (%s) %s",
                platform, command, attempt, dsl, v["diagnostic"],
            )
            continue

        # Success — freeze + materialise parsed results per-sample.
        freeze_info = freeze_parser(
            dsl, source, platform, command,
            num_samples=len(samples),
            samples_hash=_samples_hash(samples),
            contract_version=LEARNER_CONTRACT_VERSION,
        )
        newly_parsed: list[dict[str, Any]] = []
        for s, parsed in zip(samples, v["per_sample"]):
            if parsed:
                newly_parsed.append({
                    "device": s.get("device"),
                    "command": command,
                    "parsed_data": parsed,
                    "source": f"learner_{dsl}",
                })
        return "learned", newly_parsed, freeze_info

    return "failed", [], None


def _try_existing_parser(
    platform: str, command: str, samples: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """If a frozen parser already handles this command, apply it to all
    samples and return the parsed rows. Otherwise return None."""
    try:
        from olav_netops.tools.textfsm_parse import parse_output
    except Exception:
        return None
    rows: list[dict[str, Any]] = []
    ok = True
    for s in samples:
        parsed = parse_output(platform, command, s.get("raw_output") or "")
        if not parsed:
            ok = False
            break
        rows.append({
            "device": s.get("device"),
            "command": command,
            "parsed_data": parsed,
            "source": "frozen_registry",
        })
    return rows if ok and rows else None


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

def learn_commands(
    samples: list[dict[str, Any]],
    *,
    budget_seconds: int = DEFAULT_BUDGET_SECONDS,
    max_workers: int = DEFAULT_MAX_WORKERS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    allow_llm: bool = True,
    force_relearn: bool = False,
) -> LearnResult:
    """Learn parsers for every (platform, command) in ``samples`` in parallel.

    Each group is handed to a ThreadPool worker; wall-clock budget
    ``budget_seconds`` caps the whole run. Failure cache at
    ``.olav/templates/_failed_learn.json`` skips recent failures
    unless ``force_relearn`` is set.
    """
    t_start = time.time()
    result = LearnResult()

    if not samples:
        return result

    # Group by (platform, command) — keep ALL samples per group.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in samples:
        plat = s.get("platform") or "unknown"
        cmd = s.get("command") or ""
        if not cmd:
            continue
        groups.setdefault((plat, cmd), []).append(s)

    # Failure cache handling. Always load the disk cache so a successful
    # learn can wipe its own stale entry even when force_relearn bypassed
    # the skip decision.
    cache = _load_failure_cache()
    cache_dirty = False
    runnable: list[tuple[str, str, list[dict[str, Any]]]] = []
    for (plat, cmd), grp in groups.items():
        key = _cache_key(plat, cmd)
        h = _samples_hash(grp)
        if not force_relearn and key in cache and _is_fresh_failure(cache[key], h):
            result.skipped.append({
                "platform": plat, "command": cmd,
                "reason": "failure_cache_hit",
                "ttl_hint": cache[key].get("retry_after_seconds"),
            })
            continue
        runnable.append((plat, cmd, grp))

    # Concurrent execution with a cumulative wall-clock budget. The
    # budget bounds the whole run; individual workers may exceed the
    # remaining window and still complete (we don't interrupt mid-LLM-call).
    deadline = t_start + budget_seconds
    futures: dict[Future, tuple[str, str, list[dict[str, Any]]]] = {}

    nonlocal_dirty = [cache_dirty]
    recorded_keys: set[tuple[str, str]] = set()

    def _record(fut: Future) -> None:
        plat, cmd, grp = futures[fut]
        if (plat, cmd) in recorded_keys:
            return
        recorded_keys.add((plat, cmd))
        try:
            status, newly, frozen_info = fut.result()
        except Exception as exc:  # noqa: BLE001
            logger.warning("learn_commands: worker raised %s/%s: %s", plat, cmd, exc)
            result.failed.append({
                "platform": plat, "command": cmd, "reason": f"exception: {exc}",
            })
            return
        if status == "learned":
            result.newly_parsed.extend(newly)
            if frozen_info:
                result.frozen.append(frozen_info)
            key = _cache_key(plat, cmd)
            if key in cache:
                del cache[key]
                nonlocal_dirty[0] = True
        else:
            result.failed.append({
                "platform": plat, "command": cmd, "reason": "all_retries_failed",
            })
            key = _cache_key(plat, cmd)
            cache[key] = {
                "attempted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "samples_hash": _samples_hash(grp),
                "retry_after_seconds": DEFAULT_FAILURE_TTL_SECONDS,
                "contract_version": LEARNER_CONTRACT_VERSION,
                "last_error": "learner cascade produced no working parser",
            }
            nonlocal_dirty[0] = True

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for plat, cmd, grp in runnable:
            fut = ex.submit(
                _learn_one_group, plat, cmd, grp,
                max_retries=max_retries, allow_llm=allow_llm,
            )
            futures[fut] = (plat, cmd, grp)

        try:
            for fut in as_completed(list(futures), timeout=budget_seconds):
                _record(fut)
        except _FuturesTimeout:
            for fut, (plat, cmd, _grp) in futures.items():
                if not fut.done() and (plat, cmd) not in recorded_keys:
                    fut.cancel()
                    recorded_keys.add((plat, cmd))
                    result.skipped.append({
                        "platform": plat, "command": cmd,
                        "reason": "budget_exhausted",
                    })

    cache_dirty = nonlocal_dirty[0]

    if cache_dirty:
        _save_failure_cache(cache)

    result.elapsed_seconds = time.time() - t_start
    return result


# ──────────────────────────────────────────────────────────────────────────
# Module-level smoke test hook — callable from a REPL for quick check.
# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import sys
    # Minimal manual invocation — echo the API contract.
    print("learn_commands API:")
    print("  learn_commands(samples, budget_seconds, max_workers, max_retries, allow_llm, force_relearn)")
    print("  samples: list[{device, platform, command, raw_output}]")
    sys.exit(0)
