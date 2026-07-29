"""models.dev catalog connector — offering/pricing/capability/context evidence (MIT, daily).

Parses the ``https://models.dev/api.json`` shape: ``{providerId: {id, name, models: {modelId:
{...}}}}``. Emits one ``model`` record and one ``provider_offering`` record per model. Capabilities
that models.dev does not document are **omitted** (preserved as unknown), never emitted as ``False``.
"""

from __future__ import annotations

import json

from registry.normalize import canonical_model_id, known_aliases
from registry.schema import (
    ModelRecord,
    PriceObservation,
    ProviderOfferingRecord,
    Record,
    TrustLevel,
)

API_URL = "https://models.dev/api.json"


class ModelsDevConnector:
    source_id = "models.dev"
    url = API_URL
    license = "MIT"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        records: list[Record] = []
        for provider_id, provider in sorted(data.items()):
            models = provider.get("models", {})
            for model_id, model in sorted(models.items()):
                canonical = canonical_model_id(model_id, provider=provider_id)
                records.append(
                    ModelRecord(
                        source_id=self.source_id,
                        trust_level=self.trust_level,
                        id=canonical,
                        publisher=provider.get("name") or provider_id,
                        developer=model.get("developer"),
                        family=model.get("family"),
                        release_date=model.get("release_date"),
                        version=model.get("version"),
                        aliases=sorted({model_id, *known_aliases(canonical)} - {canonical}),
                    )
                )
                limit = model.get("limit") or {}
                cost = model.get("cost") or {}
                modalities = model.get("modalities") or {}
                records.append(
                    ProviderOfferingRecord(
                        source_id=self.source_id,
                        trust_level=self.trust_level,
                        model_id=canonical,
                        provider=provider_id,
                        availability_state="available",
                        modalities=sorted(set(modalities.get("input", []))),
                        context_window_tokens=limit.get("context"),
                        max_output_tokens=limit.get("output"),
                        price=PriceObservation(
                            input_usd_per_mtok=cost.get("input"),
                            output_usd_per_mtok=cost.get("output"),
                            observed_at=observed_at,
                        )
                        if cost
                        else None,
                        observed_at=observed_at,
                    )
                )
        return records
