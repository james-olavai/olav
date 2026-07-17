"""Harness profile for large-tier models — a deliberate NO-OP.

Large cloud models (deepseek-v4, gpt-4o, claude-*) are capable enough that
OLAV imposes **no** small-model discipline on them — see ``tier_small`` /
``tier_medium`` for what that discipline is and why forcing it onto a strong
model would only hurt.

deepagents, however, logs a WARNING for every pre-built model that matches
no registered profile *once any profile is registered* — and OLAV always
registers the small + medium tiers. That turns a benign "this large model
needs no discipline" into scary-looking noise on every run (printed ~3× per
agent construction):

    No harness profile matched pre-built model ChatOpenAI
    (identifier='deepseek-v4-flash', provider='openai'); using defaults.

Registering an **empty** ``HarnessProfile()`` under the configured large
model's spec makes deepagents' resolver match cleanly (stock behavior, no
discipline applied) and silences the false alarm. Keyed to the currently-
configured model only — we can't enumerate every large model in the world,
and don't need to: the warning only ever concerns the model actually loaded.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(model_specs: tuple[str, ...]) -> None:
    """Bind an empty (stock-behavior) profile to each given model spec.

    ``model_specs`` should include both the bare model identifier and the
    ``provider:model`` form so deepagents' resolver matches whichever key it
    derives from the pre-built model object.
    """
    from deepagents.profiles import HarnessProfile, register_harness_profile

    profile = HarnessProfile()  # no prompt suffix, no tool/middleware excludes
    bound = 0
    for spec in model_specs:
        if spec:
            register_harness_profile(spec, profile)
            bound += 1
    logger.debug("✓ large-tier no-op profile bound to %d model spec(s)", bound)
