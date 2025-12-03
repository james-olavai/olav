"""Test Result Cache Manager.

Tracks passed E2E tests to skip on subsequent runs, saving tokens.
Uses a JSON file to persist results across test sessions.

Features:
    - Caches passed test results with timing information
    - Skips cached tests on subsequent runs
    - Tracks performance metrics (duration, tool calls, LLM tokens)
    - Auto-invalidates cache on code changes
    - Configurable TTL (default 24 hours)

Usage:
    # In conftest.py
    from tests.e2e.test_cache import TestResultCache
    
    cache = TestResultCache()
    
    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(item):
        if cache.is_passed(item.nodeid):
            pytest.skip("Previously passed (cached)")
    
    @pytest.hookimpl(trylast=True)
    def pytest_runtest_makereport(item, call):
        if call.when == "call" and call.excinfo is None:
            cache.mark_passed(item.nodeid, duration=call.duration)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ============================================
# Performance Logging
# ============================================
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Configure performance logger
perf_logger = logging.getLogger("olav.e2e.performance")
perf_logger.setLevel(logging.DEBUG)

# File handler for performance logs
_log_file = LOG_DIR / f"e2e_performance_{datetime.now().strftime('%Y%m%d')}.log"
_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
perf_logger.addHandler(_file_handler)


@dataclass
class PerformanceMetrics:
    """Performance metrics for a test execution."""
    test_id: str
    start_time: str = ""
    end_time: str = ""
    duration_ms: float = 0.0
    tool_calls: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    steps: list[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def log_step(self, step_name: str, duration_ms: float, details: dict | None = None):
        """Log a step in the test execution."""
        step = {
            "name": step_name,
            "timestamp": datetime.now().isoformat(),
            "duration_ms": duration_ms,
            "details": details or {},
        }
        self.steps.append(step)
        perf_logger.debug(f"Step: {step_name} | {duration_ms:.2f}ms | {details}")
    
    def log_tool_call(self, tool_name: str, duration_ms: float, success: bool, input_size: int = 0, output_size: int = 0):
        """Log a tool call."""
        call = {
            "tool": tool_name,
            "timestamp": datetime.now().isoformat(),
            "duration_ms": duration_ms,
            "success": success,
            "input_size": input_size,
            "output_size": output_size,
        }
        self.tool_calls.append(call)
        perf_logger.debug(f"Tool: {tool_name} | {duration_ms:.2f}ms | success={success}")
    
    def log_llm_call(self, prompt_tokens: int, completion_tokens: int, duration_ms: float):
        """Log an LLM call."""
        self.llm_calls += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens
        perf_logger.debug(f"LLM: {prompt_tokens}+{completion_tokens} tokens | {duration_ms:.2f}ms")


class PerformanceTracker:
    """Tracks performance metrics for test execution."""
    
    def __init__(self, test_id: str):
        self.metrics = PerformanceMetrics(test_id=test_id)
        self._start_time: float | None = None
    
    def start(self):
        """Start timing."""
        self._start_time = time.perf_counter()
        self.metrics.start_time = datetime.now().isoformat()
        perf_logger.info(f"Test START: {self.metrics.test_id}")
    
    def stop(self):
        """Stop timing and calculate duration."""
        if self._start_time:
            self.metrics.duration_ms = (time.perf_counter() - self._start_time) * 1000
            self.metrics.end_time = datetime.now().isoformat()
            perf_logger.info(
                f"Test END: {self.metrics.test_id} | "
                f"Duration: {self.metrics.duration_ms:.2f}ms | "
                f"Tools: {len(self.metrics.tool_calls)} | "
                f"LLM calls: {self.metrics.llm_calls} | "
                f"Tokens: {self.metrics.total_tokens}"
            )
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


# Global tracker for current test
_current_tracker: PerformanceTracker | None = None


def get_current_tracker() -> PerformanceTracker | None:
    """Get the current performance tracker."""
    return _current_tracker


def set_current_tracker(tracker: PerformanceTracker | None):
    """Set the current performance tracker."""
    global _current_tracker
    _current_tracker = tracker


class TestResultCache:
    """Manages test result caching to skip previously passed tests."""
    
    CACHE_FILE = Path(__file__).parent / "test_results_cache.json"
    
    def __init__(self, cache_file: Path | None = None):
        """Initialize cache manager.
        
        Args:
            cache_file: Custom cache file path (default: test_results_cache.json)
        """
        self.cache_file = cache_file or self.CACHE_FILE
        self._cache = self._load_cache()
    
    def _load_cache(self) -> dict[str, Any]:
        """Load cache from JSON file."""
        if not self.cache_file.exists():
            return self._default_cache()
        
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return self._default_cache()
    
    def _default_cache(self) -> dict[str, Any]:
        """Return default cache structure."""
        return {
            "_metadata": {
                "description": "Cache of passed E2E tests with timing and performance metrics",
                "created": datetime.now().isoformat(),
                "version": "2.0",
            },
            "passed_tests": {},
            "performance_summary": {
                "total_tests": 0,
                "total_duration_ms": 0.0,
                "avg_duration_ms": 0.0,
                "total_tool_calls": 0,
                "total_llm_calls": 0,
                "total_tokens": 0,
            },
            "settings": {
                "cache_enabled": True,
                "cache_ttl_hours": 24,
                "force_rerun_on_code_change": True,
                "performance_threshold_ms": 30000,  # 30s default threshold
            },
        }
    
    def _save_cache(self) -> None:
        """Save cache to JSON file."""
        self._cache["_metadata"]["last_updated"] = datetime.now().isoformat()
        
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2, ensure_ascii=False)
    
    @property
    def enabled(self) -> bool:
        """Check if caching is enabled."""
        # Allow override via environment variable
        if os.environ.get("E2E_CACHE_DISABLED", "").lower() in ("1", "true", "yes"):
            return False
        return self._cache.get("settings", {}).get("cache_enabled", True)
    
    @property
    def ttl_hours(self) -> int:
        """Get cache TTL in hours."""
        return self._cache.get("settings", {}).get("cache_ttl_hours", 24)
    
    def _get_test_hash(self, test_id: str) -> str:
        """Generate hash for test identification.
        
        Args:
            test_id: pytest node ID (e.g., tests/e2e/test_x.py::TestClass::test_method)
            
        Returns:
            Short hash of test ID
        """
        return hashlib.md5(test_id.encode()).hexdigest()[:12]
    
    def _get_code_hash(self, test_file: str) -> str:
        """Generate hash of test file content for change detection.
        
        Args:
            test_file: Path to test file
            
        Returns:
            Hash of file content
        """
        try:
            file_path = Path(test_file)
            if file_path.exists():
                content = file_path.read_bytes()
                return hashlib.md5(content).hexdigest()[:12]
        except Exception:
            pass
        return ""
    
    def is_passed(self, test_id: str) -> bool:
        """Check if test was previously passed and still valid.
        
        Args:
            test_id: pytest node ID
            
        Returns:
            True if test can be skipped
        """
        if not self.enabled:
            return False
        
        test_hash = self._get_test_hash(test_id)
        passed_tests = self._cache.get("passed_tests", {})
        
        if test_hash not in passed_tests:
            return False
        
        entry = passed_tests[test_hash]
        
        # Check TTL
        passed_time = datetime.fromisoformat(entry["passed_at"])
        if datetime.now() - passed_time > timedelta(hours=self.ttl_hours):
            return False
        
        # Check for code changes if enabled
        if self._cache.get("settings", {}).get("force_rerun_on_code_change", True):
            test_file = test_id.split("::")[0]
            current_hash = self._get_code_hash(test_file)
            if current_hash and entry.get("code_hash") != current_hash:
                return False
        
        return True
    
    def mark_passed(
        self,
        test_id: str,
        duration_ms: float = 0.0,
        metrics: PerformanceMetrics | None = None,
    ) -> None:
        """Mark a test as passed with timing information.
        
        Args:
            test_id: pytest node ID
            duration_ms: Test duration in milliseconds
            metrics: Optional detailed performance metrics
        """
        if not self.enabled:
            return
        
        test_hash = self._get_test_hash(test_id)
        test_file = test_id.split("::")[0]
        
        entry = {
            "test_id": test_id,
            "passed_at": datetime.now().isoformat(),
            "code_hash": self._get_code_hash(test_file),
            "duration_ms": duration_ms,
        }
        
        # Add detailed metrics if available
        if metrics:
            entry["performance"] = {
                "duration_ms": metrics.duration_ms,
                "tool_calls": len(metrics.tool_calls),
                "llm_calls": metrics.llm_calls,
                "total_tokens": metrics.total_tokens,
                "prompt_tokens": metrics.prompt_tokens,
                "completion_tokens": metrics.completion_tokens,
                "steps": len(metrics.steps),
            }
            # Update performance summary
            self._update_performance_summary(metrics)
        
        self._cache.setdefault("passed_tests", {})[test_hash] = entry
        self._save_cache()
    
    def _update_performance_summary(self, metrics: PerformanceMetrics) -> None:
        """Update aggregate performance summary."""
        summary = self._cache.setdefault("performance_summary", {
            "total_tests": 0,
            "total_duration_ms": 0.0,
            "avg_duration_ms": 0.0,
            "total_tool_calls": 0,
            "total_llm_calls": 0,
            "total_tokens": 0,
        })
        
        summary["total_tests"] += 1
        summary["total_duration_ms"] += metrics.duration_ms
        summary["avg_duration_ms"] = summary["total_duration_ms"] / summary["total_tests"]
        summary["total_tool_calls"] += len(metrics.tool_calls)
        summary["total_llm_calls"] += metrics.llm_calls
        summary["total_tokens"] += metrics.total_tokens
    
    def mark_failed(self, test_id: str) -> None:
        """Remove a test from cache when it fails.
        
        Args:
            test_id: pytest node ID
        """
        test_hash = self._get_test_hash(test_id)
        passed_tests = self._cache.get("passed_tests", {})
        
        if test_hash in passed_tests:
            del passed_tests[test_hash]
            self._save_cache()
    
    def clear(self) -> None:
        """Clear all cached results."""
        self._cache["passed_tests"] = {}
        self._save_cache()
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dict with cache stats
        """
        passed_tests = self._cache.get("passed_tests", {})
        valid_count = sum(1 for tid in passed_tests if self.is_passed(passed_tests[tid].get("test_id", "")))
        
        # Calculate timing stats
        durations = [
            entry.get("duration_ms", 0)
            for entry in passed_tests.values()
            if entry.get("duration_ms", 0) > 0
        ]
        
        return {
            "total_cached": len(passed_tests),
            "valid_cached": valid_count,
            "cache_enabled": self.enabled,
            "ttl_hours": self.ttl_hours,
            "timing": {
                "total_duration_ms": sum(durations),
                "avg_duration_ms": sum(durations) / len(durations) if durations else 0,
                "min_duration_ms": min(durations) if durations else 0,
                "max_duration_ms": max(durations) if durations else 0,
            },
            "performance": self._cache.get("performance_summary", {}),
        }
    
    def get_slow_tests(self, threshold_ms: float | None = None) -> list[dict]:
        """Get tests that exceeded performance threshold.
        
        Args:
            threshold_ms: Custom threshold (uses setting if None)
            
        Returns:
            List of slow test entries
        """
        threshold = threshold_ms or self._cache.get("settings", {}).get("performance_threshold_ms", 30000)
        passed_tests = self._cache.get("passed_tests", {})
        
        slow_tests = []
        for entry in passed_tests.values():
            duration = entry.get("duration_ms", 0)
            if duration > threshold:
                slow_tests.append({
                    "test_id": entry.get("test_id"),
                    "duration_ms": duration,
                    "passed_at": entry.get("passed_at"),
                    "performance": entry.get("performance", {}),
                })
        
        return sorted(slow_tests, key=lambda x: x["duration_ms"], reverse=True)


# Singleton instance
_cache_instance: TestResultCache | None = None


def get_cache() -> TestResultCache:
    """Get singleton cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = TestResultCache()
    return _cache_instance
