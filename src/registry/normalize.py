"""Advisory identity crosswalk — proposed, never imposed.

Design decision (refines ADR 0028 §3): **the registry preserves every source-native identifier
verbatim on the evidence records and never merges ids.** Identity is a curation/scope decision, and
a wrong merge done centrally is invisible to every consumer — exactly the "manufacture equivalence"
the ADR forbids. So the crosswalk lives here as a *separate advisory sidecar*: it suggests which
source-native ids are probably the same model. A consumer maps *its* inventory against these
suggestions (adopting, overriding, or ignoring them); the registry does not decide.

The proposal is deliberately conservative. A canonical id is emitted **only** when an explicit,
reviewed identity table maps the source-native id (``method="reviewed_alias"``). Everything else is
honestly ``method="unmapped"`` with ``canonical_model_id=None`` — never a value manufactured from
the access ``service_id`` or a provider label, and never fuzzy-matched. A false merge is worse than
an unmapped id a consumer can map by hand.

Canonical slug policy: a reviewed canonical id may be developer-prefixed (``openai/gpt-oss-120b``)
**only** when the developer organization and the model equivalence have both been explicitly
reviewed and recorded in ``_REVIEWED_IDENTITY`` below. Lowercasing a free-text provider or developer
label is never sufficient, and an embedded ``/`` in a source-native id is opaque source data — its
first segment is never interpreted as a developer.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from registry.schema import (
    ClaimRecord,
    CrosswalkEntry,
    EvaluationResultRecord,
    ModelRecord,
    ProviderOfferingRecord,
    Record,
)


class ReviewedIdentity(NamedTuple):
    developer_id: str | None
    canonical_model_id: str


# Explicit, reviewed identities only. The key is a lowercased source-native model id (as some source
# emits it); the value is the reviewed developer id and canonical model id. Because the same model is
# served under different source-native ids across access services, every known spelling is listed so
# that, e.g., Cerebras' ``gpt-oss-120b`` and Groq's ``openai/gpt-oss-120b`` resolve to one canonical
# id. Absence means "no reviewed identity" — the entry is emitted as ``unmapped``.
_REVIEWED_IDENTITY: dict[str, ReviewedIdentity] = {
    "claude-opus-4": ReviewedIdentity("anthropic", "anthropic/claude-opus-4"),
    "anthropic/claude-opus-4": ReviewedIdentity("anthropic", "anthropic/claude-opus-4"),
    "gpt-5": ReviewedIdentity("openai", "openai/gpt-5"),
    "openai/gpt-5": ReviewedIdentity("openai", "openai/gpt-5"),
    "gpt-oss-120b": ReviewedIdentity("openai", "openai/gpt-oss-120b"),
    "openai/gpt-oss-120b": ReviewedIdentity("openai", "openai/gpt-oss-120b"),
}


def propose_canonical(
    source_model_id: str,
) -> tuple[str | None, str | None, Literal["reviewed_alias", "unmapped"]]:
    """Return ``(canonical_model_id, developer_id, method)``. Deterministic; conservative.

    The canonical id comes *only* from the reviewed identity table. There is no provider-prefix
    fallback: an unreviewed id — with or without an embedded slash — is ``unmapped``/``None``.
    """
    reviewed = _REVIEWED_IDENTITY.get(source_model_id.strip().lower())
    if reviewed is not None:
        return reviewed.canonical_model_id, reviewed.developer_id, "reviewed_alias"
    return None, None, "unmapped"


class _Identity(NamedTuple):
    source_id: str
    service_id: str | None
    source_provider_id: str | None
    source_model_id: str


def _identity_of(record: Record) -> _Identity | None:
    """Extract the full source offering identity from any record that carries a model identity."""
    if isinstance(record, ModelRecord):
        return _Identity(record.source_id, None, None, record.source_model_id)
    if isinstance(record, ProviderOfferingRecord):
        return _Identity(record.source_id, record.service_id, record.source_provider_id, record.source_model_id)
    if isinstance(record, (EvaluationResultRecord, ClaimRecord)):
        return _Identity(record.source_id, None, None, record.source_model_id)
    return None


def build_crosswalk(records: list[Record]) -> list[CrosswalkEntry]:
    """Build one advisory crosswalk entry per distinct full source offering identity.

    Keying by ``(source_id, service_id, source_provider_id, source_model_id)`` — the complete
    offering identity — makes the retained entry independent of record emission order, and the final
    deterministic sort makes the serialized output byte-stable regardless of input ordering.
    """
    seen: dict[_Identity, CrosswalkEntry] = {}
    for record in records:
        identity = _identity_of(record)
        if identity is None or identity in seen:
            continue
        canonical, developer_id, method = propose_canonical(identity.source_model_id)
        seen[identity] = CrosswalkEntry(
            source_id=identity.source_id,
            service_id=identity.service_id,
            source_provider_id=identity.source_provider_id,
            source_model_id=identity.source_model_id,
            developer_id=developer_id,
            canonical_model_id=canonical,
            method=method,
        )
    return [seen[key] for key in sorted(seen, key=lambda i: tuple("" if v is None else v for v in i))]
