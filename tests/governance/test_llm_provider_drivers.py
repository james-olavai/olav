"""Every provider OLAV can select must have its driver declared.

This class of defect appeared three times on 2026-08-04 alone:

  1. `core/llm.py` imports `langchain_google_genai` for the Google AI Studio
     branch while pyproject declared only the raw `google-genai` SDK — the
     driver arrived as a THIRD-order transitive of deepagents-code, which is
     upper-bounded `<0.1.17`.
  2. `core/llm.py` inferred `model_provider="deepseek"` (and groq / together /
     perplexity) from base_url with none of those packages declared, so
     `api.deepseek.com` in api.json raised
     `ImportError: Initializing ChatDeepSeek requires the langchain-deepseek
     package` inside init_chat_model.
  3. The first-run wizard listed DeepSeek and OpenRouter with
     `model_provider="openai"` specifically to dodge the dependency — silently
     trading away DeepSeek's strict schema validation, which needs the vendor
     driver's beta endpoint.

Each was a code path written without its dependency. A static gate closes the
class: if a provider is selectable, its driver is installable.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# model_provider values that are NOT langchain-<name> packages.
_NOT_A_DRIVER_PACKAGE = {
    # ChatOpenAI, from langchain-openai — used for every generic
    # OpenAI-compatible endpoint (local llama.cpp / vLLM / unknown base_url).
    "openai": "langchain-openai",
    "anthropic": "langchain-anthropic",
    "ollama": "langchain-ollama",
    "google_genai": "langchain-google-genai",
}


def _declared() -> tuple[set[str], dict[str, set[str]]]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    def _names(specs):
        return {s.split(">")[0].split("=")[0].split("[")[0].strip() for s in specs}
    core = _names(data["project"]["dependencies"])
    extras = {k: _names(v) for k, v in
              data["project"].get("optional-dependencies", {}).items()}
    return core, extras


def _package_for(model_provider: str) -> str:
    return _NOT_A_DRIVER_PACKAGE.get(
        model_provider, f"langchain-{model_provider.replace('_', '-')}")


def test_every_wizard_provider_has_a_declared_driver():
    """A menu entry whose driver is missing is a choice the install cannot honour.

    Same failure the on-CPU embedding option had: the wizard promised something
    and the first real call raised ImportError. Entries that legitimately need an
    extra declare it via `Provider.extra`, and the wizard refuses them up front
    with the install command.
    """
    from olav.cli.llm_setup import PROVIDERS

    core, extras = _declared()
    problems = []
    for p in PROVIDERS:
        pkg = _package_for(p.model_provider)
        if p.extra:
            if pkg not in extras.get(p.extra, set()):
                problems.append(
                    f"{p.label}: model_provider={p.model_provider!r} claims extra "
                    f"{p.extra!r}, but {pkg} is not declared there")
        elif pkg not in core:
            problems.append(
                f"{p.label}: model_provider={p.model_provider!r} needs {pkg}, "
                f"which is not a core dependency — declare it, or mark the entry "
                f"with extra=...")
    assert not problems, "wizard offers providers whose drivers are missing:\n  " + \
        "\n  ".join(problems)


def test_every_inferable_provider_has_a_declared_driver():
    """`llm.py` infers model_provider from base_url; each must be installable.

    A hand-edited api.json never goes through the wizard, so the inference table
    is a second, independent way to select a provider — and it was the one that
    ImportError'd.
    """
    src = (REPO / "src" / "olav" / "core" / "llm.py").read_text(encoding="utf-8")
    marker = "Auto-detect provider from base_url"
    assert marker in src, "inference block not found — has llm.py been restructured?"
    block = src[src.index(marker):]
    block = block[: block.index("streaming")]
    # Accept either assignment shape. This test first parsed only
    # `params["model_provider"] = "x"` and broke the moment the block was
    # refactored to stage the value in `_inferred` before a driver-availability
    # check — a gate keyed to one spelling of the code it guards is brittle in a
    # way that reads as a real failure.
    inferred = set(re.findall(
        r'(?:params\["model_provider"\]|_inferred)\s*=\s*"([a-z_]+)"', block))
    assert inferred, (
        "no inferred providers parsed out of the base_url block — the assignment "
        "shape changed again; update the pattern rather than deleting the gate"
    )

    core, _ = _declared()
    missing = sorted(
        f"{prov} -> {_package_for(prov)}"
        for prov in inferred
        if _package_for(prov) not in core
    )
    assert not missing, (
        "llm.py can infer these providers but their drivers are not declared, so a "
        "matching base_url in api.json raises ImportError inside init_chat_model:\n  "
        + "\n  ".join(missing)
    )


def test_declared_drivers_are_actually_importable():
    """Declared is not installed. Checked from the real environment."""
    core, _ = _declared()
    drivers = sorted(p for p in core if p.startswith("langchain-"))
    missing = [d for d in drivers
               if importlib.util.find_spec(d.replace("-", "_")) is None]
    assert not missing, f"declared but not importable: {missing}"


def test_tool_call_knobs_cover_every_selectable_provider():
    """The determinism table must know about every provider we can select.

    An unlisted provider silently gets no tuning — which is the safe direction,
    but silent. Failing here forces the table to be updated deliberately, with a
    signature check, rather than a provider quietly opting out of strict schema
    validation.
    """
    from olav.cli.llm_setup import PROVIDERS
    from olav.core.llm import _TOOL_CALL_KNOBS

    unknown = sorted({p.model_provider for p in PROVIDERS} - set(_TOOL_CALL_KNOBS))
    assert not unknown, (
        "providers missing from core/llm.py:_TOOL_CALL_KNOBS: " + ", ".join(unknown)
        + "\nAdd them with the knobs their bind_tools() signature actually accepts "
          "— passing an unsupported one is a TypeError."
    )


@pytest.mark.parametrize("provider,knob", [
    ("deepseek", "strict"),
    ("deepseek", "parallel_tool_calls"),
    ("openrouter", "strict"),
    ("perplexity", "strict"),
    ("anthropic", "strict"),
    ("anthropic", "parallel_tool_calls"),
])
def test_declared_knobs_match_the_real_bind_tools_signature(provider, knob):
    """The table claims a knob — the driver must really accept it.

    Measured, not assumed: groq and mistralai take neither `strict` nor
    `parallel_tool_calls`, perplexity takes `strict` but not
    `parallel_tool_calls`. Getting this wrong is a TypeError at the first tool
    call, i.e. in production rather than here.
    """
    import inspect

    mod = importlib.import_module(f"langchain_{provider}")
    cls = next(
        getattr(mod, n) for n in dir(mod)
        if n.startswith("Chat") and isinstance(getattr(mod, n), type)
    )
    params = inspect.signature(cls.bind_tools).parameters
    assert knob in params, (
        f"_TOOL_CALL_KNOBS says {provider} accepts {knob!r}, but "
        f"{cls.__name__}.bind_tools does not take it"
    )
