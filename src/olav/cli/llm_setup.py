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
    # Name of the extra that ships this provider's driver, when it is not a
    # default dependency. Mistral's driver pulls `tokenizers` (+28MB), the same
    # weight this release moved behind `[local-embed]`, so it stays opt-in — and
    # the wizard reports the install command instead of offering a choice the
    # install cannot honour, which is the trap the on-CPU embed option fell into.
    extra: str = ""


# base_url None → prompt for it (Custom). "" → the client's own default (OpenAI).
# Each entry carries the provider's REAL ``model_provider``, so init_chat_model
# loads that vendor's driver rather than routing everything through ChatOpenAI +
# base_url.
#
# DeepSeek and OpenRouter used to be listed as ``"openai"`` here, with a comment
# saying it "avoids the optional langchain-openrouter dependency". That traded
# away real behaviour: DeepSeek's ``strict`` schema validation only works against
# its **beta** endpoint, which ChatDeepSeek switches to and a plain ChatOpenAI
# cannot reach — and strict schema enforcement is the protocol-layer fix for
# malformed tool-call arguments (CLAUDE.md: fix arg shape at the coercion layer,
# not with prompt imperatives). The drivers are declared dependencies now; see
# ``core/llm.py:_TOOL_CALL_KNOBS`` for what each one actually supports.
#
# The one exception is deliberate: a **local** OpenAI-compatible server
# (llama.cpp / vLLM) really is generic, so ``"openai"`` is correct there rather
# than a compromise.
# Mistral was removed 2026-08-06: it was selectable in this menu while its
# driver shipped only in the `[mistral]` extra, so a plain install offered a
# provider it could not construct. It was also one of nine providers that had
# never had a request sent to it. Re-adding it means shipping the driver by
# default (+28MB, pulls `tokenizers` back) or accepting that gap knowingly, plus
# a request-payload test — see tests/governance/test_provider_request_payload.py.
PROVIDERS: list[Provider] = [
    Provider("OpenAI", "openai", "", True),
    Provider("DeepSeek", "deepseek", "https://api.deepseek.com/v1", True,
             hint="e.g. deepseek-chat (deepseek-reasoner has no tool calling)"),
    Provider("OpenRouter", "openrouter", "https://openrouter.ai/api/v1", True),
    Provider("Anthropic (Claude)", "anthropic", "", False,
             hint="e.g. claude-sonnet-4-5, claude-opus-4-1"),
    Provider("Google AI Studio (Gemini)", "google_genai", "", False,
             hint="e.g. gemini-2.5-flash, gemma-4-31b-it"),
    Provider("xAI (Grok)", "xai", "https://api.x.ai/v1", True),
    Provider("Groq", "groq", "https://api.groq.com/openai/v1", True),
    Provider("Together AI", "together", "https://api.together.xyz/v1", True),
    Provider("Perplexity", "perplexity", "https://api.perplexity.ai", True),
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


def _driver_available(provider: "Provider") -> bool:
    """Is this provider's langchain driver importable?

    Only meaningful for entries with an ``extra``: everything else is a declared
    dependency and always present. Uses ``find_spec`` so probing cannot execute
    the package.

    LEGACY-KEEP: no provider currently declares an ``extra`` — Mistral, the only
    one that did, was removed 2026-08-06. The machinery stays because it guards a
    real trap: a wizard that accepts a provider whose driver is missing writes a
    config that only fails later, at the first real call, long after it said
    everything was fine (the on-CPU embedding option had exactly this bug). The
    next provider shipped in an extra needs the guard, not a rewrite of it.
    """
    if not provider.extra:
        return True
    import importlib.util

    module = f"langchain_{provider.model_provider}"
    return importlib.util.find_spec(module) is not None


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
        _need = "" if _driver_available(p) else f"  [yellow]needs olav\\[{p.extra}][/yellow]"
        console.print(f"  {i}) {p.label}  [dim]{endpoint}[/dim]{_need}")

    choice = prompt_cls.ask(
        "Select a provider",
        choices=[str(i) for i in range(1, len(PROVIDERS) + 1)],
        default="1",
    )
    provider = PROVIDERS[int(choice) - 1]

    # A provider whose driver ships in an extra must not be silently accepted:
    # writing the config would leave init_chat_model raising ImportError on the
    # first real call, long after the wizard said everything was fine. Same
    # failure the on-CPU embedding option used to have.
    if not _driver_available(provider):
        console.print(
            f"[yellow]{provider.label} needs its driver, which is not in the "
            f"default install:[/yellow]\n"
            f"  [bold]pip install 'olav\\[{provider.extra}]'[/bold]\n"
            f"[dim]Install it and re-run, or pick another provider.[/dim]\n"
        )
        return None

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


# A commonly-used on-CPU model, kept as the menu default for option 3.
# NOT a fallback: on-CPU embedding needs the ``[local-embed]`` extra.
_DEFAULT_LOCAL_EMBED = "BAAI/bge-small-zh-v1.5"

# Curated lightweight on-CPU sentence-transformers models.
# (label, HF model id) — kept short; a user can always type their own.
_LOCAL_EMBED_MODELS = [
    ("Multilingual, balanced zh+en (~470MB)", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
    ("English, small (~130MB)", "BAAI/bge-small-en-v1.5"),
    ("English, higher quality (~440MB)", "BAAI/bge-base-en-v1.5"),
]

# How many times the menu is re-offered before giving up. Bounded so a
# non-TTY misuse cannot spin forever.
_EMBED_SETUP_ATTEMPTS = 3


def _local_embed_installed() -> bool:
    """Whether the ``[local-embed]`` extra is installed (see ``embedder``).

    A thin wrapper, not a second implementation: it keeps the monkeypatch seam
    the wizard tests need while ``core.embedder.local_embed_available`` stays
    the single source of truth shared with ``olav doctor``.
    """
    from olav.core.embedder import local_embed_available

    return local_embed_available()


def interactive_embedding_setup(console, *, prompt_cls=None) -> dict | None:
    """First-run embedding config (dev_docs/99 §7.8, dev_docs/114).

    A **required** step, not an opt-in. Until 2026-08-04 pressing Enter kept
    an on-CPU default (``BAAI/bge-small-zh-v1.5``, offline, zero-config);
    sentence-transformers now ships in the ``[local-embed]`` extra, so on a
    default install there is no such default to fall back to. Every exit is
    therefore explicit: either a backend that answered a live probe, or a
    confirmed skip persisted as ``mode: "none"``.

    That explicitness is the point — a silent degrade here costs the user
    memory, recall and semantic routing with no message saying so.

    Returns the ``embedding`` config dict to persist, or None if the user
    never reached a decision (caller leaves api.json untouched).
    """
    if prompt_cls is None:
        from rich.prompt import Prompt as prompt_cls  # noqa: N813

    console.print("\n[bold]Configure embedding backend[/bold]")
    console.print("[dim]Powers memory, recall and semantic routing. "
                  "Without one, those features are off.[/dim]")

    for _attempt in range(_EMBED_SETUP_ATTEMPTS):
        installed = _local_embed_installed()
        console.print("  1) Self-hosted embedding server (Ollama / llama.cpp / vLLM)"
                      "  [dim]OpenAI-compatible[/dim]")
        console.print("  2) Cloud OpenAI-compatible endpoint")
        # NB: `\[` escapes the bracket for rich's markup parser — an unescaped
        # "[local-embed]" is read as a style tag and silently swallowed, so the
        # user would be told to run `pip install olav` with the extra missing.
        console.print("  3) On-CPU model, no server  [dim]"
                      + ("needs no server; slower" if installed
                         else "NOT INSTALLED — needs `pip install olav\\[local-embed]`")
                      + "[/dim]")
        console.print("  4) Skip  [dim]memory / recall / semantic routing stay off[/dim]")
        choice = prompt_cls.ask("Select", choices=["1", "2", "3", "4"], default="1")

        if choice == "4":
            if _confirm_skip_embedding(console, prompt_cls):
                return {"mode": "none"}
            continue

        if choice == "3":
            if not installed:
                # Actionable, not a bare ImportError later: on-CPU embedding is
                # a deliberate choice, and it is one `pip install` away.
                console.print(
                    "[yellow]On-CPU embedding needs the optional extra:[/yellow]\n"
                    "  [bold]pip install 'olav\\[local-embed]'[/bold]  "
                    "[dim](pulls torch — ~4.6 GB on linux-x86_64)[/dim]\n"
                    "[dim]Install it and re-run, or pick 1 / 2 to use a server "
                    "instead.[/dim]\n"
                )
                continue
            emb = _local_embedding_model(console, prompt_cls)
            if emb is not None:
                return emb
            continue

        emb = _api_embedding_backend(console, prompt_cls, cloud=(choice == "2"))
        if emb is not None:
            return emb

    console.print(
        f"[yellow]No embedding backend configured after {_EMBED_SETUP_ATTEMPTS} "
        "attempts — leaving it unset. Memory and recall stay off until you set "
        "`embedding` in .olav/config/api.json or run "
        '`olav --agent admin "switch embedding …"`.[/yellow]\n'
    )
    return None


def _confirm_skip_embedding(console, prompt_cls) -> bool:
    """Make the cost of skipping explicit before accepting it."""
    console.print(
        "[yellow]Skipping embedding disables memory, recall and semantic "
        "routing.[/yellow] [dim]Agents still answer, but nothing is remembered "
        "between sessions and routing falls back to keywords.[/dim]"
    )
    return prompt_cls.ask(
        "Continue without embedding?", choices=["y", "n"], default="n"
    ) == "y"


def _api_embedding_backend(console, prompt_cls, *, cloud: bool) -> dict | None:
    """Endpoint → key → model → live probe, for ``mode: "api"``.

    Returns None (caller re-offers the menu) on any incomplete answer or a
    failed probe — never a silent "keep the default", because there is no
    default to keep.
    """
    if cloud:
        base_url = prompt_cls.ask(
            "Endpoint base_url (e.g. https://api.openai.com/v1)"
        ).strip()
        if not base_url:
            console.print("[yellow]A base_url is required for a cloud endpoint.[/yellow]\n")
            return None
        api_key = prompt_cls.ask("API key", password=True).strip()
        if not api_key:
            console.print("[yellow]A cloud endpoint needs an API key.[/yellow]\n")
            return None
    else:
        base_url = prompt_cls.ask(
            "Embedding server base_url", default="http://localhost:11434/v1"
        ).strip()
        if not base_url:
            console.print("[yellow]A base_url is required.[/yellow]\n")
            return None
        api_key = prompt_cls.ask(
            "API key (Enter for a local placeholder)", password=True
        ).strip() or "local"

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
        console.print("[yellow]An embedding model name is required.[/yellow]\n")
        return None

    overrides = {"mode": "api", "model": model, "base_url": base_url, "api_key": api_key}
    if not _validate_embedding(console, overrides):
        return None
    return {"mode": "api", "api": {"model": model, "base_url": base_url, "api_key": api_key}}


def _local_embedding_model(console, prompt_cls) -> dict | None:
    console.print("[dim]On-CPU sentence-transformers models "
                  f"(e.g. {_DEFAULT_LOCAL_EMBED}):[/dim]")
    for i, (label, mid) in enumerate(_LOCAL_EMBED_MODELS, 1):
        console.print(f"  {i}) {mid}  [dim]{label}[/dim]")
    pick = prompt_cls.ask("Select a model (number, or type an HF model id)", default="1").strip()
    if pick.isdigit() and 1 <= int(pick) <= len(_LOCAL_EMBED_MODELS):
        model = _LOCAL_EMBED_MODELS[int(pick) - 1][1]
    elif pick:
        model = pick
    else:
        console.print("[yellow]A model id is required.[/yellow]\n")
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
    # Deliberately does NOT offer to "keep the local default" — that default
    # no longer exists on a install without `[local-embed]`, so reassuring the
    # user here would hand them a silently embedding-less setup.
    console.print(
        f"[yellow]Embedding backend not reachable:[/yellow] {detail}\n"
        "[dim]Nothing was saved. Check the endpoint / key / model name and try "
        "again, or pick 4 to go without embedding.[/dim]\n"
    )
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
