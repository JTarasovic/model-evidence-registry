"""Advisory identity crosswalk — proposed, never imposed.

Design decision (refines ADR 0028 §3): **the registry preserves every source-native identifier
verbatim on the evidence records and never merges ids.** Identity is a curation/scope decision, and
a wrong merge done centrally is invisible to every consumer — exactly the "manufacture equivalence"
the ADR forbids. So the crosswalk lives here as a *separate advisory sidecar*: it suggests which
source-native ids are probably the same model. A consumer maps *its* inventory against these
suggestions (adopting, overriding, or ignoring them); the registry does not decide.

The proposal is deliberately conservative: only an explicit, reviewed alias table performs a real
merge (``method="alias_table"``). Everything else is passed through with an id-normalization only
(``method="verbatim"``) — no fuzzy matching, because a false merge is worse than an unmerged id a
consumer can map by hand.
"""

from __future__ import annotations

from typing import Literal

from registry.schema import (
    ClaimRecord,
    CrosswalkEntry,
    EvaluationResultRecord,
    ModelRecord,
    ProviderOfferingRecord,
    Record,
)

# Explicit, reviewed aliases only. Left side is a lowercased source-native id; right side is the
# proposed canonical id. Absence means "no merge" — the id passes through normalized-only.
_ALIASES: dict[str, str] = {
    "claude-opus-4": "anthropic/claude-opus-4",
    "anthropic/claude-opus-4": "anthropic/claude-opus-4",
    "gpt-5": "openai/gpt-5",
    "openai/gpt-5": "openai/gpt-5",
}


def propose_canonical(
    raw: str, *, provider: str | None = None
) -> tuple[str, Literal["alias_table", "verbatim"]]:
    """Return ``(proposed_canonical_id, method)``. Deterministic; conservative."""
    key = raw.strip().lower()
    if key in _ALIASES:
        return _ALIASES[key], "alias_table"
    if "/" in raw:
        return key, "verbatim"
    if provider:
        return f"{provider.strip().lower()}/{key}", "verbatim"
    return key, "verbatim"


def _identity_of(record: Record) -> tuple[str, str, str | None] | None:
    """Extract ``(source, raw_id, provider)`` from any record that carries a model identity."""
    if isinstance(record, ModelRecord):
        return record.source_id, record.id, None
    if isinstance(record, ProviderOfferingRecord):
        return record.source_id, record.model_id, record.provider
    if isinstance(record, (EvaluationResultRecord, ClaimRecord)):
        return record.source_id, record.model_id, None
    return None


def build_crosswalk(records: list[Record]) -> list[CrosswalkEntry]:
    """Build one advisory crosswalk entry per distinct ``(source, raw_id)`` seen across the records."""
    seen: dict[tuple[str, str], CrosswalkEntry] = {}
    for record in records:
        identity = _identity_of(record)
        if identity is None:
            continue
        source, raw_id, provider = identity
        dedup_key = (source, raw_id)
        if dedup_key in seen:
            continue
        canonical, method = propose_canonical(raw_id, provider=provider)
        seen[dedup_key] = CrosswalkEntry(
            source=source,
            raw_id=raw_id,
            provider=provider,
            proposed_canonical_id=canonical,
            method=method,
        )
    return [seen[k] for k in sorted(seen)]
