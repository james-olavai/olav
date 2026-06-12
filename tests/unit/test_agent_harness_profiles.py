"""Tests for ``olav.agents.profiles`` — OLAV-owned deepagents harness profiles.

Profiles encode per-tier discipline declaratively (system-prompt
suffix, excluded tools/middleware) instead of scattered ``if
model.startswith("gemma")`` branches in ``agent.py``.  Tiering follows
``olav.core.config._TIER_REGEX_SMALL`` / ``_TIER_REGEX_MEDIUM``.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test gets a fresh registration view — the underlying
    deepagents registry is process-global, so we toggle our internal
    ``_REGISTERED`` flag back to ``False`` before each test to force
    re-registration."""
    import olav.agents.profiles as _p
    _saved = _p._REGISTERED
    _p._REGISTERED = False
    yield
    _p._REGISTERED = _saved


class TestRegistration:
    def test_register_olav_profiles_idempotent(self):
        from olav.agents.profiles import register_olav_profiles
        register_olav_profiles()
        register_olav_profiles()  # second call — must not raise

    def test_registration_flag_flips(self):
        import olav.agents.profiles as _p
        assert _p._REGISTERED is False
        _p.register_olav_profiles()
        assert _p._REGISTERED is True


class TestSmallTierProfile:
    """gemma / phi-3 / 7B-8B llama / qwen-7b / haiku family."""

    @pytest.fixture
    def profile(self):
        from olav.agents.profiles import register_olav_profiles
        register_olav_profiles()
        from deepagents.profiles.harness.harness_profiles import _get_harness_profile
        return _get_harness_profile("gemma4:31b")

    def test_resolves_for_gemma4_31b(self, profile):
        assert profile is not None

    def test_suffix_mentions_small_model_discipline(self, profile):
        suffix = (profile.system_prompt_suffix or "").lower()
        assert "discipline" in suffix
        # Suffix has markdown emphasis around "one"; match surrounding phrase
        assert "tool call per turn" in suffix

    def test_excludes_auto_injected_tools(self, profile):
        """The eight deepagents-injected tools that small models reach
        for unprompted must be in the exclusion list — defense in depth
        with the post-compile prune in ``agent.py``."""
        expected = {
            "write_todos", "ls", "glob", "grep",
            "read_file", "write_file", "edit_file", "execute",
        }
        assert expected.issubset(profile.excluded_tools)

    def test_excludes_todo_middleware(self, profile):
        assert "TodoListMiddleware" in profile.excluded_middleware

    def test_bound_to_multiple_small_model_specs(self):
        """gemma4 variants + non-gemma small models (phi-3, llama-3.1:8b,
        qwen2.5:7b, haiku-4-5) all share the same small-tier profile."""
        from olav.agents.profiles import register_olav_profiles
        register_olav_profiles()
        from deepagents.profiles.harness.harness_profiles import _get_harness_profile
        for variant in (
            "gemma4:31b", "gemma4:9b", "gemma:2b",
            "phi-3:mini",
            "llama-3.1:8b", "llama-3.2:3b",
            "qwen2.5:7b",
            "haiku-4-5",
            "x-ai/grok-4.1-fast",
        ):
            assert _get_harness_profile(variant) is not None, (
                f"{variant} should resolve to the small-tier profile"
            )

    def test_bound_to_gguf_format_specs(self):
        """llama.cpp gguf model names (via OpenAI-compat endpoint) must resolve
        to the small-tier profile — the current production model uses this format."""
        from olav.agents.profiles import register_olav_profiles
        register_olav_profiles()
        from deepagents.profiles.harness.harness_profiles import _get_harness_profile
        for variant in (
            "openai:gemma-4-31b-it-Q4_K_M.gguf",
            "openai:gemma-4-27b-it-Q4_K_M.gguf",
            "openai:gemma-4-9b-it-Q4_K_M.gguf",
            "openai:gemma-4-31b-it-Q8_0.gguf",
        ):
            p = _get_harness_profile(variant)
            assert p is not None, f"{variant} should resolve to the small-tier profile"
            assert bool(p.excluded_tools), f"{variant} profile has no excluded_tools"


class TestMediumTierProfile:
    @pytest.fixture
    def profile(self):
        from olav.agents.profiles import register_olav_profiles
        register_olav_profiles()
        from deepagents.profiles.harness.harness_profiles import _get_harness_profile
        return _get_harness_profile("qwen3.6:27b")

    def test_resolves_for_qwen36_27b(self, profile):
        assert profile is not None

    def test_suffix_softer_than_small(self, profile):
        """Medium-tier suffix exists but is lighter — no aggressive tool
        exclusions, just one-tool-per-turn discipline."""
        suffix = (profile.system_prompt_suffix or "").lower()
        assert "discipline" in suffix
        assert "tool call per turn" in suffix

    def test_keeps_filesystem_and_todo_tools(self, profile):
        """Medium models handle write_todos / file ops competently —
        the profile keeps them available."""
        keep = {"write_todos", "read_file", "ls", "glob", "grep"}
        leaked = keep & profile.excluded_tools
        assert not leaked, (
            f"medium-tier should keep {keep}; profile excludes {leaked}"
        )
        assert "TodoListMiddleware" not in profile.excluded_middleware

    def test_bound_to_medium_specs(self):
        from olav.agents.profiles import register_olav_profiles
        register_olav_profiles()
        from deepagents.profiles.harness.harness_profiles import _get_harness_profile
        for variant in (
            "qwen3.6:27b", "qwen3:30b", "qwen3:14b",
            "qwen2.5:14b", "qwen2.5:32b", "qwen2.5-coder:32b",
            "mixtral:8x7b",
            "openai:qwen2.5-32b-instruct",
            "openai:qwen3-32b",
        ):
            assert _get_harness_profile(variant) is not None, (
                f"{variant} should resolve to the medium-tier profile"
            )


class TestNoLeakage:
    def test_large_models_get_no_profile(self):
        """Large-tier (GPT-4 / Claude Sonnet / Opus) intentionally has
        no OLAV profile — deepagents stock behavior is fine."""
        from olav.agents.profiles import register_olav_profiles
        register_olav_profiles()
        from deepagents.profiles.harness.harness_profiles import _get_harness_profile
        # gpt-4-turbo / claude-sonnet-4-6 / claude-opus-4-7 should not
        # accidentally pick up small or medium tier discipline.
        for big in ("gpt-4-turbo", "claude-sonnet-4-6", "claude-opus-4-7"):
            assert _get_harness_profile(big) is None, (
                f"{big} should NOT match an OLAV-registered profile"
            )
