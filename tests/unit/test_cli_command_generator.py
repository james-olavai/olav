"""
Unit tests for CLI Command Generator.

Tests LLM-based platform-specific command generation with caching.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olav.tools.cli_command_generator import (
    CLICommandGenerator,
    generate_platform_command,
    get_command_generator,
    CommandGeneratorResult,
)


class TestCLICommandGenerator:
    """Tests for CLICommandGenerator class."""

    def test_init_default(self):
        """Test default initialization."""
        generator = CLICommandGenerator()
        assert generator.cache_ttl == 3600
        assert generator._llm is None

    def test_init_custom_ttl(self):
        """Test custom cache TTL."""
        generator = CLICommandGenerator(cache_ttl=7200)
        assert generator.cache_ttl == 7200

    def test_generate_cache_key(self):
        """Test cache key generation."""
        generator = CLICommandGenerator()
        key1 = generator._generate_cache_key("show bgp", "cisco_ios", "")
        key2 = generator._generate_cache_key("show bgp", "cisco_ios", "")
        key3 = generator._generate_cache_key("show bgp", "cisco_iosxr", "")

        assert key1 == key2  # Same inputs
        assert key1 != key3  # Different platform
        assert len(key1) == 16  # Truncated hash

    @pytest.mark.asyncio
    async def test_get_from_cache_miss(self):
        """Test cache miss returns None."""
        generator = CLICommandGenerator()

        with patch("olav.tools.cli_command_generator.get_cache_manager") as mock_cache:
            mock_cache.return_value.get = AsyncMock(return_value=None)
            result = await generator._get_from_cache("test_key")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_from_cache_hit(self):
        """Test cache hit returns cached result."""
        generator = CLICommandGenerator()
        cached_data = '{"commands": ["show version"], "explanation": "test", "warnings": [], "alternatives": []}'

        with patch("olav.tools.cli_command_generator.get_cache_manager") as mock_cache:
            mock_cache.return_value.get = AsyncMock(return_value=cached_data)
            result = await generator._get_from_cache("test_key")

            assert result is not None
            assert result["commands"] == ["show version"]
            assert result["cached"] is True

    @pytest.mark.asyncio
    async def test_set_to_cache(self):
        """Test setting cache value."""
        generator = CLICommandGenerator()
        result: CommandGeneratorResult = {
            "commands": ["show version"],
            "explanation": "Shows device version",
            "warnings": [],
            "alternatives": [],
            "cached": False,
        }

        with patch("olav.tools.cli_command_generator.get_cache_manager") as mock_cache:
            mock_cache.return_value.set = AsyncMock()
            await generator._set_to_cache("test_key", result)

            mock_cache.return_value.set.assert_called_once()
            # Verify cached flag is removed before storing
            call_args = mock_cache.return_value.set.call_args
            assert "cached" not in call_args[0][1] or '"cached"' not in call_args[0][1]

    @pytest.mark.asyncio
    async def test_generate_with_cache_hit(self):
        """Test generate returns cached result."""
        generator = CLICommandGenerator()
        cached_result: CommandGeneratorResult = {
            "commands": ["show ip bgp summary"],
            "explanation": "Shows BGP summary",
            "warnings": [],
            "alternatives": [],
            "cached": True,
        }

        with patch.object(generator, "_get_from_cache", return_value=cached_result):
            result = await generator.generate(
                intent="show bgp status",
                platform="cisco_ios",
            )

            assert result["commands"] == ["show ip bgp summary"]
            assert result["cached"] is True

    @pytest.mark.asyncio
    async def test_generate_with_llm(self):
        """Test generate calls LLM when cache miss."""
        generator = CLICommandGenerator()

        # Mock cache miss
        with patch.object(generator, "_get_from_cache", return_value=None):
            with patch.object(generator, "_set_to_cache", new_callable=AsyncMock):
                # Mock prompt manager
                with patch("olav.tools.cli_command_generator.prompt_manager") as mock_pm:
                    mock_pm.load_prompt.return_value = "test prompt"

                    # Mock LLM response
                    mock_llm = MagicMock()
                    mock_response = MagicMock()
                    mock_response.content = '{"commands": ["show version"], "explanation": "test", "warnings": [], "alternatives": []}'
                    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
                    generator._llm = mock_llm

                    result = await generator.generate(
                        intent="show device version",
                        platform="cisco_ios",
                    )

                    assert result["commands"] == ["show version"]
                    assert result["cached"] is False
                    mock_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_without_cache(self):
        """Test generate skips cache when use_cache=False."""
        generator = CLICommandGenerator()

        with patch.object(generator, "_get_from_cache") as mock_get:
            with patch.object(generator, "_set_to_cache") as mock_set:
                # Mock LLM
                with patch("olav.tools.cli_command_generator.prompt_manager") as mock_pm:
                    mock_pm.load_prompt.return_value = "test prompt"

                    mock_llm = MagicMock()
                    mock_response = MagicMock()
                    mock_response.content = '{"commands": [], "explanation": "", "warnings": [], "alternatives": []}'
                    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
                    generator._llm = mock_llm

                    await generator.generate(
                        intent="test",
                        platform="cisco_ios",
                        use_cache=False,
                    )

                    mock_get.assert_not_called()
                    mock_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_llm_error(self):
        """Test generate handles LLM errors gracefully."""
        generator = CLICommandGenerator()

        with patch.object(generator, "_get_from_cache", return_value=None):
            with patch("olav.tools.cli_command_generator.prompt_manager") as mock_pm:
                mock_pm.load_prompt.return_value = "test prompt"

                mock_llm = MagicMock()
                mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
                generator._llm = mock_llm

                result = await generator.generate(
                    intent="test",
                    platform="cisco_ios",
                )

                assert result["commands"] == []
                assert "LLM error" in result["warnings"][0]
                assert result["cached"] is False

    @pytest.mark.asyncio
    async def test_generate_prompt_not_found(self):
        """Test generate handles missing prompt template."""
        generator = CLICommandGenerator()

        with patch.object(generator, "_get_from_cache", return_value=None):
            with patch("olav.tools.cli_command_generator.prompt_manager") as mock_pm:
                mock_pm.load_prompt.side_effect = FileNotFoundError("not found")

                result = await generator.generate(
                    intent="test",
                    platform="cisco_ios",
                )

                assert result["commands"] == []
                assert "Prompt template not found" in result["explanation"]

    @pytest.mark.asyncio
    async def test_generate_parses_markdown_json(self):
        """Test generate extracts JSON from markdown code blocks."""
        generator = CLICommandGenerator()

        with patch.object(generator, "_get_from_cache", return_value=None):
            with patch.object(generator, "_set_to_cache", new_callable=AsyncMock):
                with patch("olav.tools.cli_command_generator.prompt_manager") as mock_pm:
                    mock_pm.load_prompt.return_value = "test prompt"

                    # LLM response with markdown code block
                    mock_llm = MagicMock()
                    mock_response = MagicMock()
                    mock_response.content = '''Here is the command:
```json
{"commands": ["show interfaces"], "explanation": "test", "warnings": [], "alternatives": []}
```
'''
                    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
                    generator._llm = mock_llm

                    result = await generator.generate(
                        intent="show interfaces",
                        platform="cisco_ios",
                    )

                    assert result["commands"] == ["show interfaces"]


class TestGetCommandGenerator:
    """Tests for get_command_generator function."""

    def test_returns_singleton(self):
        """Test returns same instance."""
        # Reset global
        import olav.tools.cli_command_generator as module
        module._generator = None

        gen1 = get_command_generator()
        gen2 = get_command_generator()

        assert gen1 is gen2


class TestGeneratePlatformCommand:
    """Tests for generate_platform_command convenience function."""

    @pytest.mark.asyncio
    async def test_delegates_to_generator(self):
        """Test function delegates to generator instance."""
        with patch("olav.tools.cli_command_generator.get_command_generator") as mock_get:
            mock_generator = MagicMock()
            mock_generator.generate = AsyncMock(return_value={
                "commands": ["show version"],
                "explanation": "test",
                "warnings": [],
                "alternatives": [],
                "cached": False,
            })
            mock_get.return_value = mock_generator

            result = await generate_platform_command(
                intent="show version",
                platform="cisco_ios",
            )

            assert result["commands"] == ["show version"]
            mock_generator.generate.assert_called_once_with(
                intent="show version",
                platform="cisco_ios",
                available_commands=None,
                context="",
            )

    @pytest.mark.asyncio
    async def test_passes_all_parameters(self):
        """Test all parameters are passed to generator."""
        with patch("olav.tools.cli_command_generator.get_command_generator") as mock_get:
            mock_generator = MagicMock()
            mock_generator.generate = AsyncMock(return_value={
                "commands": [],
                "explanation": "",
                "warnings": [],
                "alternatives": [],
                "cached": False,
            })
            mock_get.return_value = mock_generator

            await generate_platform_command(
                intent="check bgp",
                platform="juniper_junos",
                available_commands=["show bgp summary"],
                context="core router",
            )

            mock_generator.generate.assert_called_once_with(
                intent="check bgp",
                platform="juniper_junos",
                available_commands=["show bgp summary"],
                context="core router",
            )
