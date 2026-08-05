"""Cerebras's public model catalog connector.

Cerebras publishes an unauthenticated ``/public/v1/models`` endpoint with its current inference
offerings.  The connector retains the catalog's source-native model IDs and declared availability,
modality, limits, capability (tool use / reasoning / structured output), and pricing facts, but
emits only a hash for the source response.
"""

from __future__ import annotations

import json
from typing import Any

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, PriceObservation, ProviderOfferingRecord, Record, TrustLevel

PUBLIC_MODELS_URL = "https://api.cerebras.ai/public/v1/models"


def _positive_int(value: Any) -> int | None:
    """Return a source-declared positive integer token limit, if present."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _per_mtok(value: Any) -> float | None:
    """Convert Cerebras's documented USD-per-token price to USD-per-million-tokens."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    try:
        return float(value) * 1_000_000
    except ValueError:
        return None


def _modalities(model: dict[str, Any]) -> list[str]:
    """Keep the source-native architecture modality label when it is declared."""
    architecture = model.get("architecture")
    modality = architecture.get("modality") if isinstance(architecture, dict) else None
    return [modality] if isinstance(modality, str) and modality else []


def _capability(model: dict[str, Any], key: str) -> bool | None:
    """Read one source-documented capability boolean from Cerebras's ``capabilities`` map.

    None when the map or the key is absent (undocumented); a documented ``false`` is kept as
    ``False`` — a real negative assertion, distinct from absence.
    """
    capabilities = model.get("capabilities")
    value = capabilities.get(key) if isinstance(capabilities, dict) else None
    return value if isinstance(value, bool) else None


class CerebrasModelsConnector:
    """Parse directly available Cerebras inference models from its public catalog."""

    source_id = "cerebras-models"
    fixture_filename = "cerebras-models.json"
    url = PUBLIC_MODELS_URL
    license = "Cerebras public models endpoint terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    fetch_policy = FetchPolicy(source_key="cerebras-models", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        catalog = json.loads(body)
        if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
            raise ValueError("Cerebras public models catalog must be an object with a data list")

        records: list[Record] = [
            DocumentRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                url=self.url,
                kind="api_doc",
                content_sha256=sha256_hex(body),
                retrieved_at=observed_at,
                redistribution_policy="hash_and_facts_only",
            )
        ]
        for model in sorted(catalog["data"], key=lambda item: item.get("id", "") if isinstance(item, dict) else ""):
            if not isinstance(model, dict) or not isinstance(model_id := model.get("id"), str) or not model_id:
                continue
            limits = model.get("limits")
            pricing = model.get("pricing")
            limits = limits if isinstance(limits, dict) else {}
            pricing = pricing if isinstance(pricing, dict) else {}
            input_price = _per_mtok(pricing.get("prompt"))
            output_price = _per_mtok(pricing.get("completion"))
            records.append(
                ProviderOfferingRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    source_model_id=model_id,
                    service_id="cerebras",
                    source_provider_label="Cerebras",
                    availability_state="unavailable" if model.get("deprecated") is True else "available",
                    modalities=_modalities(model),
                    context_window_tokens=_positive_int(limits.get("max_context_length")),
                    max_output_tokens=_positive_int(limits.get("max_completion_tokens")),
                    tool_use=_capability(model, "function_calling"),
                    reasoning=_capability(model, "reasoning"),
                    structured_output=_capability(model, "structured_outputs"),
                    price=PriceObservation(
                        input_usd_per_mtok=input_price,
                        output_usd_per_mtok=output_price,
                        observed_at=observed_at,
                    )
                    if input_price is not None or output_price is not None
                    else None,
                    observed_at=observed_at,
                )
            )
        return records
