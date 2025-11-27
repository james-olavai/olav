#!/usr/bin/env python
"""Test script for i18n functionality in Deep Dive workflow."""

from olav.workflows.deep_dive import tr
from config.settings import AgentConfig


def test_i18n_strings():
    """Test all language strings."""
    test_cases = [
        ("plan_title", {}),
        ("ready_section", {"count": 5}),
        ("query_complete", {"table": "BGP Neighbors", "count": 10}),
        ("state_established", {}),
        ("state_not_established", {}),
        ("table_bgp", {}),
        ("field_hostname", {}),
        ("task_complete_msg", {"task_id": 1, "table": "BGP", "count": 5}),
    ]

    for lang in ["zh", "en", "ja"]:
        AgentConfig.LANGUAGE = lang  # type: ignore
        print(f"\n{'='*50}")
        print(f"Language: {lang.upper()}")
        print("=" * 50)
        
        for key, kwargs in test_cases:
            result = tr(key, **kwargs)
            print(f"  {key}: {result}")


if __name__ == "__main__":
    test_i18n_strings()
