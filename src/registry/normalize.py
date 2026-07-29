"""Identity crosswalk — reconcile aliases and provider/reasoning variants without false equivalence.

Design §3: the crosswalk keys on canonical ``model`` × ``provider`` × (reasoning-effort / agent-
harness) so aliases and variants reconcile *without ever being collapsed into one row*. For the PoC
this is a small, explicit alias table plus a deterministic normalizer — no fuzzy matching, because a
wrong merge here silently manufactures the exact equivalence ADR 0028 forbids.
"""

from __future__ import annotations

# Explicit, reviewed aliases only. Left side is a lowercased provider-or-vendor model string as it
# appears in a source; right side is the canonical id. Absence means "leave as-is" — never guess.
_ALIASES: dict[str, str] = {
    "claude-opus-4": "anthropic/claude-opus-4",
    "anthropic/claude-opus-4": "anthropic/claude-opus-4",
    "gpt-5": "openai/gpt-5",
    "openai/gpt-5": "openai/gpt-5",
}


def canonical_model_id(raw: str, *, provider: str | None = None) -> str:
    """Best-effort canonical id. Deterministic; returns a namespaced id when the alias is known,
    otherwise a stable ``provider/raw`` (or ``raw``) form — it does not invent equivalence."""
    key = raw.strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    if "/" in raw:
        return raw.strip().lower()
    if provider:
        return f"{provider.strip().lower()}/{key}"
    return key


def known_aliases(canonical: str) -> list[str]:
    """Every raw string that maps to ``canonical`` (for the ``model`` record's ``aliases``)."""
    return sorted({raw for raw, canon in _ALIASES.items() if canon == canonical and raw != canonical})
