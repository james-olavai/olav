"""Tests for entry-point-based domain prompt discovery.

Verifies that ``get_domain_prompt()`` uses ``importlib.metadata.entry_points``
instead of hardcoded imports from ``olav_netops``.
"""

from __future__ import annotations

import importlib
import inspect
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from olav.cli.main import get_domain_prompt

GENERIC_FALLBACK = "You are an AI Operations Assistant."


class TestDomainPromptDiscovery:
    """get_domain_prompt() uses entry_points(group='olav.domain_prompts')."""

    def test_no_entry_points_returns_generic_fallback(self) -> None:
        """When no domain prompt entry points exist, returns the generic fallback."""
        with patch("olav.cli.main.entry_points", return_value=[]):
            result = get_domain_prompt()
        assert result == GENERIC_FALLBACK

    def test_single_entry_point_returns_its_value(self) -> None:
        """When one entry point exists, returns the prompt from that entry point."""
        fake_ep = MagicMock()
        fake_ep.load.return_value = "You are a Network Operations AI."

        with patch("olav.cli.main.entry_points", return_value=[fake_ep]):
            result = get_domain_prompt()

        fake_ep.load.assert_called_once()
        assert result == "You are a Network Operations AI."

    def test_multiple_entry_points_returns_first(self) -> None:
        """When multiple entry points exist, returns the first one found."""
        ep1 = MagicMock()
        ep1.load.return_value = "First domain prompt."
        ep2 = MagicMock()
        ep2.load.return_value = "Second domain prompt."

        with patch("olav.cli.main.entry_points", return_value=[ep1, ep2]):
            result = get_domain_prompt()

        ep1.load.assert_called_once()
        ep2.load.assert_not_called()
        assert result == "First domain prompt."

    def test_entry_point_load_error_falls_back_with_warning(self) -> None:
        """When an entry point fails to load, logs a warning and returns fallback."""
        broken_ep = MagicMock()
        broken_ep.name = "broken"
        broken_ep.load.side_effect = Exception("import failed")

        with (
            patch("olav.cli.main.entry_points", return_value=[broken_ep]),
            patch("olav.cli.main.logger") as mock_logger,
        ):
            result = get_domain_prompt()

        assert result == GENERIC_FALLBACK
        mock_logger.warning.assert_called_once()

    def test_no_hardcoded_olav_netops_import(self) -> None:
        """The function must NOT contain a hardcoded import from olav_netops."""
        source = inspect.getsource(get_domain_prompt)
        assert "olav_netops" not in source, (
            "get_domain_prompt() must not hardcode 'olav_netops' import — "
            "use importlib.metadata.entry_points instead"
        )

    def test_uses_entry_points_group(self) -> None:
        """The function must call entry_points with group='olav.domain_prompts'."""
        with patch("olav.cli.main.entry_points", return_value=[]) as mock_ep:
            get_domain_prompt()
        mock_ep.assert_called_once_with(group="olav.domain_prompts")
