"""OpenRouter connector — an **evidence source only**, never a benchmark authority (ADR 0028 §3).

Parses ``https://openrouter.ai/api/v1/models`` (``{data: [{id, context_length, pricing:{prompt,
completion}, architecture:{input_modalities}}]}``). Emits ``provider_offering`` availability/pricing/
context evidence under provider ``openrouter`` (an aggregator observation), plus a ``model`` record.
Capability booleans (tool use / reasoning / structured output) are derived from the per-model
``supported_parameters`` enumeration.
Pricing on OpenRouter is per-token USD; converted to per-Mtok for a like-for-like observation.
"""

from __future__ import annotations

import json

from registry.fetch import FetchPolicy
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


def _supports(entry: dict, parameter: str) -> bool | None:
    """Map one OpenRouter ``supported_parameters`` flag to a capability boolean.

    ``supported_parameters`` is a per-model enumeration of the request parameters the model accepts,
    so its presence documents the full set: the parameter's presence is ``True``, its absence from a
    listed set is a documented ``False``. A missing/blank list is undocumented → ``None``.
    """
    supported = entry.get("supported_parameters")
    if not isinstance(supported, list) or not supported:
        return None
    return parameter in supported


class OpenRouterConnector:
    source_id = "openrouter"
    url = API_URL
    license = "Provider ToS"
    parser_version = "1"
    trust_level = TrustLevel.THIRD_PARTY_REPORT
    fetch_policy = FetchPolicy()

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        records: list[Record] = []
        for entry in sorted(data.get("data", []), key=lambda e: e.get("id", "")):
            raw_id = entry.get("id", "")
            pricing = entry.get("pricing") or {}
            architecture = entry.get("architecture") or {}
            records.append(
                ModelRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    source_model_id=raw_id,
                )
            )
            records.append(
                ProviderOfferingRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    source_model_id=raw_id,
                    service_id="openrouter",
                    availability_state="available",
                    modalities=sorted(set(architecture.get("input_modalities", []))),
                    context_window_tokens=entry.get("context_length"),
                    tool_use=_supports(entry, "tools"),
                    reasoning=_supports(entry, "reasoning"),
                    structured_output=_supports(entry, "structured_outputs"),
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
