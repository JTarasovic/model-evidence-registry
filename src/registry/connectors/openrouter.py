"""OpenRouter connector — an **evidence source only**, never a benchmark authority (ADR 0028 §3).

Parses ``https://openrouter.ai/api/v1/models`` (``{data: [{id, context_length, pricing:{prompt,
completion}, architecture:{input_modalities}}]}``). Emits ``provider_offering`` availability/pricing/
context evidence under provider ``openrouter`` (an aggregator observation), plus a ``model`` record.
Pricing on OpenRouter is per-token USD; converted to per-Mtok for a like-for-like observation.
"""

from __future__ import annotations

import json

from registry.normalize import canonical_model_id
from registry.schema import (
    ModelRecord,
    PriceObservation,
    ProviderOfferingRecord,
    Record,
    TrustLevel,
)

API_URL = "https://openrouter.ai/api/v1/models"


def _per_mtok(per_token: str | float | None) -> float | None:
    if per_token in (None, ""):
        return None
    try:
        return float(per_token) * 1_000_000
    except (TypeError, ValueError):
        return None


class OpenRouterConnector:
    source_id = "openrouter"
    url = API_URL
    license = "Provider ToS"
    parser_version = "1"
    trust_level = TrustLevel.THIRD_PARTY_REPORT

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        records: list[Record] = []
        for entry in sorted(data.get("data", []), key=lambda e: e.get("id", "")):
            raw_id = entry.get("id", "")
            canonical = canonical_model_id(raw_id)
            pricing = entry.get("pricing") or {}
            architecture = entry.get("architecture") or {}
            records.append(
                ModelRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    id=canonical,
                    aliases=sorted({raw_id} - {canonical}),
                )
            )
            records.append(
                ProviderOfferingRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    model_id=canonical,
                    provider="openrouter",
                    availability_state="available",
                    modalities=sorted(set(architecture.get("input_modalities", []))),
                    context_window_tokens=entry.get("context_length"),
                    price=PriceObservation(
                        input_usd_per_mtok=_per_mtok(pricing.get("prompt")),
                        output_usd_per_mtok=_per_mtok(pricing.get("completion")),
                        observed_at=observed_at,
                    )
                    if pricing
                    else None,
                    observed_at=observed_at,
                )
            )
        return records
