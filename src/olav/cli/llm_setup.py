"""Interactive first-run LLM provider setup (dev_docs/99 §7.8).

Replaces the "assume OpenAI + gpt-4o" default with the mainstream
agent-tool onboarding: pick a provider (endpoint auto-filled, or custom),
enter the key, auto-detect the available models via the provider's
OpenAI-compatible ``/models`` endpoint, pick one, then validate the whole
candidate against the live provider before writing anything.

Deterministic and zero-LLM: the provider menu is a static table and
``/models`` is a plain HTTP GET — no model call is made to *choose* the
config, only the §3.1 ``check_connectivity`` probe to *confirm* it. TTY
only; the non-interactive path (CI / piped) stays on the plain
api.json / env-var flow in ``main.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Provider:
    label: str
    model_provider: str          # langchain model_provider written to api.json
    base_url: str                # "" = provider default (OpenAI); None = ask
    lists_models: bool           # True → GET {base_url}/models with Bearer key
    key_optional: bool = False   # local servers accept a placeholder key
    hint: str = ""               # a couple of example model ids when listing is skipped


# base_url None → prompt for it (Custom). "" → the client's own default (OpenAI).
# OpenRouter/DeepSeek/local are OpenAI-compatible, so model_provider="openai"
# (avoids the optional langchain-openrouter dependency) with an explicit base_url.
PROVIDERS: list[Provider] = [
    Provider("OpenAI", "openai", "", True),
    Provider("DeepSeek", "openai", "https://api.deepseek.com/v1", True),
    Provider("OpenRouter", "openai", "https://openrouter.ai/api/v1", True),
    Provider("Anthropic (Claude)", "anthropic", "", False,
             hint="e.g. claude-sonnet-4-5, claude-opus-4-1"),
    Provider("Local server (Ollama / llama.cpp / vLLM)", "openai",
             "http://localhost:11434/v1", True, key_optional=True),
    Provider("Custom (enter your own base_url)", "openai", None, True),
]

_MODEL_MENU_CAP = 25  # above this, prompt to type instead of a giant menu


def _fetch_models(base_url: str, api_key: str) -> list[str]:
    """GET {base_url}/models (OpenAI-compat) and return sorted model ids.

    Empty list on any failure — the caller falls back to a typed prompt.
    Separated out so tests can monkeypatch it without network.
    """
    import json
    import urllib.request

    url = (base_url.rstrip("/") if base_url else "https://api.openai.com/v1") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — user-entered endpoint
            data = json.loads(resp.read().decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return sorted(ids)
    except Exception as exc:  # noqa: BLE001
        logger.debug("model listing failed for %s: %s", url, exc)
        return []


def interactive_llm_setup(console, *, prompt_cls=None) -> dict | None:
    """Run the provider → key → model → validate flow.

    Returns the ``llm`` config dict to persist
    ({provider, model_provider, model, base_url, api_key}) or None if the
    user aborted (empty input at a required step, or gave up after
    validation retries). Assumes a TTY — the caller gates on that.
    """
    if prompt_cls is None:
        from rich.prompt import Prompt as prompt_cls  # noqa: N813

    console.print("\n[bold]Configure your LLM provider[/bold]")
    for i, p in enumerate(PROVIDERS, 1):
        endpoint = p.base_url if p.base_url else ("(default)" if p.base_url == "" else "(you'll enter it)")
        console.print(f"  {i}) {p.label}  [dim]{endpoint}[/dim]")

    choice = prompt_cls.ask(
        "Select a provider",
        choices=[str(i) for i in range(1, len(PROVIDERS) + 1)],
        default="1",
    )
    provider = PROVIDERS[int(choice) - 1]

    # Endpoint
    base_url = provider.base_url
    if base_url is None:  # Custom
        base_url = prompt_cls.ask("Enter the OpenAI-compatible base_url "
                                  "(e.g. http://host:8000/v1)").strip()
        if not base_url:
            console.print("[yellow]No base_url entered — aborting setup.[/yellow]")
            return None

    # Key
    key_prompt = "Paste your API key" + (" (or press Enter for a local placeholder)"
                                         if provider.key_optional else "")
    api_key = prompt_cls.ask(key_prompt, password=True).strip()
    if not api_key:
        if provider.key_optional:
            api_key = "local"  # local servers ignore the value but the client needs one
        else:
            console.print("[yellow]No key entered — set it later in .olav/config/api.json.[/yellow]")
            return None

    # Model — auto-detect, else type
    model = _select_model(console, provider, base_url, api_key, prompt_cls)
    if not model:
        return None

    # Validate the whole candidate before writing (§3.1 shared probe)
    llm = {
        "provider": provider.model_provider,
        "model_provider": provider.model_provider,
        "model": model,
        "api_key": api_key,
    }
    if base_url:
        llm["base_url"] = base_url

    for attempt in range(3):
        console.print("[dim]Verifying the provider is reachable…[/dim]")
        from olav.core.llm import LLMFactory

        ok, detail = LLMFactory.check_connectivity(overrides={
            "model": model, "model_provider": provider.model_provider,
            "base_url": base_url or "", "api_key": api_key,
        })
        if ok:
            console.print(f"[green]✓[/green] {provider.label} / {model} — connected.\n")
            return llm
        console.print(f"[red]Could not reach the provider:[/red] {detail}")
        if attempt < 2 and prompt_cls.ask(
            "Try a different model or key?", choices=["y", "n"], default="y"
        ) == "y":
            model = _select_model(console, provider, base_url, api_key, prompt_cls) or model
            llm["model"] = model
            new_key = prompt_cls.ask("API key (Enter to keep current)", password=True).strip()
            if new_key:
                api_key = new_key
                llm["api_key"] = api_key
            continue
        break

    console.print("[yellow]Saving the config anyway — fix it later with "
                  "`olav doctor` / `olav --agent admin \"switch my LLM …\"`.[/yellow]\n")
    return llm


_DEFAULT_LOCAL_EMBED = "BAAI/bge-small-zh-v1.5"

# Curated lightweight local sentence-transformers alternatives to the default.
# (label, HF model id) — kept short; a user can always type their own.
_LOCAL_EMBED_MODELS = [
    ("Multilingual, balanced zh+en (~470MB)", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
    ("English, small (~130MB)", "BAAI/bge-small-en-v1.5"),
    ("English, higher quality (~440MB)", "BAAI/bge-base-en-v1.5"),
]


def interactive_embedding_setup(console, *, prompt_cls=None) -> dict | None:
    """Optional first-run embedding config (dev_docs/99 §7.8).

    Only reached when the user opts in — the default (local
    ``BAAI/bge-small-zh-v1.5``, offline, zero-config) is kept by pressing
    Enter in ``_ensure_bootstrapped``. This walks the three meaningful
    alternatives (local Ollama/llama.cpp server, cloud OpenAI-compat, or a
    different bundled sentence-transformers model), validated against the
    live backend before returning.

    Returns the ``embedding`` config dict to persist, or None to keep the
    default / on abort.
    """
    if prompt_cls is None:
        from rich.prompt import Prompt as prompt_cls  # noqa: N813

    console.print("\n[bold]Configure embedding backend[/bold]")
    console.print("  1) Local server (Ollama / llama.cpp / vLLM)  [dim]OpenAI-compatible[/dim]")
    console.print("  2) Cloud OpenAI-compatible endpoint")
    console.print("  3) A different local (CPU) model")
    choice = prompt_cls.ask("Select", choices=["1", "2", "3"], default="1")

    if choice == "3":
        return _local_embedding_model(console, prompt_cls)

    # API modes (local server or cloud) — mode=api with base_url.
    if choice == "1":
        base_url = prompt_cls.ask(
            "Embedding server base_url", default="http://localhost:11434/v1"
        ).strip()
        api_key = prompt_cls.ask(
            "API key (Enter for a local placeholder)", password=True
        ).strip() or "local"
    else:
        base_url = prompt_cls.ask("Endpoint base_url (e.g. https://api.openai.com/v1)").strip()
        if not base_url:
            console.print("[yellow]No base_url — keeping the local default.[/yellow]")
            return None
        api_key = prompt_cls.ask("API key", password=True).strip()
        if not api_key:
            console.print("[yellow]No key — keeping the local default.[/yellow]")
            return None

    models = _fetch_models(base_url, api_key)
    menu = models[:_MODEL_MENU_CAP]
    if menu:
        console.print("[dim]Models reported by the endpoint (chat + embedding are mixed — "
                      "pick an EMBEDDING model):[/dim]")
        for i, mm in enumerate(menu, 1):
            console.print(f"  {i}) {mm}")
    model = prompt_cls.ask("Embedding model name (number, or type a name)").strip()
    if model.isdigit() and 1 <= int(model) <= len(menu):
        model = menu[int(model) - 1]
    if not model:
        console.print("[yellow]No model — keeping the local default.[/yellow]")
        return None

    overrides = {"mode": "api", "model": model, "base_url": base_url, "api_key": api_key}
    if not _validate_embedding(console, overrides):
        return None
    return {"mode": "api", "api": {"model": model, "base_url": base_url, "api_key": api_key}}


def _local_embedding_model(console, prompt_cls) -> dict | None:
    console.print("[dim]Local sentence-transformers models "
                  f"(default is {_DEFAULT_LOCAL_EMBED}):[/dim]")
    for i, (label, mid) in enumerate(_LOCAL_EMBED_MODELS, 1):
        console.print(f"  {i}) {mid}  [dim]{label}[/dim]")
    pick = prompt_cls.ask("Select a model (number, or type an HF model id)", default="1").strip()
    if pick.isdigit() and 1 <= int(pick) <= len(_LOCAL_EMBED_MODELS):
        model = _LOCAL_EMBED_MODELS[int(pick) - 1][1]
    elif pick:
        model = pick
    else:
        return None
    console.print(f"[dim]Downloading / loading {model} (first use may take a moment)…[/dim]")
    if not _validate_embedding(console, {"mode": "local", "model": model}):
        return None
    return {"mode": "local", "local": {"model": model}}


def _validate_embedding(console, overrides: dict) -> bool:
    from olav.core.llm import LLMFactory

    ok, detail = LLMFactory.check_embedding_connectivity(overrides=overrides, strict=True)
    if ok:
        console.print("[green]✓[/green] embedding backend reachable.\n")
        return True
    console.print(f"[yellow]Embedding backend not reachable ({detail}) — "
                  "keeping the local default. Change later with "
                  '`olav --agent admin "switch embedding …"`.[/yellow]\n')
    return False


def _select_model(console, provider: Provider, base_url: str, api_key: str, prompt_cls) -> str:
    """Auto-detect models via /models and let the user pick, else type."""
    models = _fetch_models(base_url, api_key) if provider.lists_models else []

    if not models:
        hint = f" ({provider.hint})" if provider.hint else ""
        return prompt_cls.ask(f"Enter the model name{hint}").strip()

    if len(models) > _MODEL_MENU_CAP:
        console.print(f"[dim]{len(models)} models available.[/dim]")
        example = ", ".join(models[:3])
        return prompt_cls.ask(f"Enter the model name (e.g. {example})").strip()

    console.print("[dim]Available models:[/dim]")
    for i, m in enumerate(models, 1):
        console.print(f"  {i}) {m}")
    pick = prompt_cls.ask(
        "Select a model (number, or type a name)",
        default="1",
    ).strip()
    if pick.isdigit() and 1 <= int(pick) <= len(models):
        return models[int(pick) - 1]
    return pick  # typed a custom name
