"""models.dev catalog connector — offering/pricing/capability/context evidence (MIT, daily).

Parses the ``https://models.dev/api.json`` shape: ``{providerId: {id, name, models: {modelId:
{...}}}}``. Emits one ``model`` record and one ``provider_offering`` record per model. Capabilities
that models.dev does not document (the key is absent) are **omitted** (preserved as unknown), never
emitted as ``False``. models.dev documents ``tool_call`` and ``reasoning`` per model — a documented
``false`` from the source is still passed through as ``False``, distinct from an absent key.

Identifiers are emitted **source-native, verbatim** — the model's key as models.dev states it. Any
cross-source identity linkage is the advisory crosswalk's job (``normalize.build_crosswalk``), never
a mutation of the id here.
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

API_URL = "https://models.dev/api.json"


class ModelsDevConnector:
    source_id = "models.dev"
    url = API_URL
    license = "MIT"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    fetch_policy = FetchPolicy()

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        records: list[Record] = []
        for provider_id, provider in sorted(data.items()):
            models = provider.get("models", {})
            for model_id, model in sorted(models.items()):
                records.append(
                    ModelRecord(
                        source_id=self.source_id,
                        trust_level=self.trust_level,
                        source_model_id=model_id,
                        publisher=provider.get("name") or provider_id,
                        developer=model.get("developer"),
                        family=model.get("family"),
                        release_date=model.get("release_date"),
                        version=model.get("version"),
                    )
                )
                limit = model.get("limit") or {}
                cost = model.get("cost") or {}
                modalities = model.get("modalities") or {}
                records.append(
                    ProviderOfferingRecord(
                        source_id=self.source_id,
                        trust_level=self.trust_level,
                        source_model_id=model_id,
                        # models.dev is an aggregator catalog: ``provider_id`` is the source's own
                        # provider key, not a registry-owned access service. Keep it verbatim as the
                        # source provider; leave ``service_id`` null rather than inferring one from
                        # this display/machine string.
                        service_id=None,
                        source_provider_id=provider_id,
                        source_provider_label=provider.get("name"),
                        availability_state="available",
                        modalities=sorted(set(modalities.get("input", []))),
                        context_window_tokens=limit.get("context"),
                        max_output_tokens=limit.get("output"),
                        tool_use=model.get("tool_call"),
                        reasoning=model.get("reasoning"),
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
