"""Test Result Cache Manager.

Tracks passed E2E tests to skip on subsequent runs, saving tokens.
Uses a JSON file to persist results across test sessions.

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
            cache.mark_passed(item.nodeid)
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


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
                "description": "Cache of passed E2E tests to skip on subsequent runs",
                "created": datetime.now().isoformat(),
                "version": "1.0",
            },
            "passed_tests": {},
            "settings": {
                "cache_enabled": True,
                "cache_ttl_hours": 24,
                "force_rerun_on_code_change": True,
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
    
    def mark_passed(self, test_id: str) -> None:
        """Mark a test as passed.
        
        Args:
            test_id: pytest node ID
        """
        if not self.enabled:
            return
        
        test_hash = self._get_test_hash(test_id)
        test_file = test_id.split("::")[0]
        
        self._cache.setdefault("passed_tests", {})[test_hash] = {
            "test_id": test_id,
            "passed_at": datetime.now().isoformat(),
            "code_hash": self._get_code_hash(test_file),
        }
        
        self._save_cache()
    
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
        
        return {
            "total_cached": len(passed_tests),
            "valid_cached": valid_count,
            "cache_enabled": self.enabled,
            "ttl_hours": self.ttl_hours,
        }


# Singleton instance
_cache_instance: TestResultCache | None = None


def get_cache() -> TestResultCache:
    """Get singleton cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = TestResultCache()
    return _cache_instance
