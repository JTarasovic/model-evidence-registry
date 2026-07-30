"""GitHub Models catalog connector.

GitHub publishes its Models catalog as an unauthenticated JSON listing.  The connector retains
the catalog's source-native model IDs and available capability/limit facts, while emitting only a
content hash for the source document rather than redistributing the catalog response.
"""

from __future__ import annotations

import json
from typing import Any

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODELS_CATALOG_URL = "https://models.github.ai/catalog/models"


def _string_list(value: Any) -> list[str]:
    """Return source values that are explicitly strings, preserving their order and spelling."""
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _positive_int(value: Any) -> int | None:
    """Keep a declared token limit only when the catalog presents it as an integer."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


class GitHubModelsConnector:
    """Parse available model offerings from GitHub's public Models catalog."""

    source_id = "github-models"
    fixture_filename = "github-models.json"
    url = MODELS_CATALOG_URL
    license = "GitHub Models catalog terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    fetch_policy = FetchPolicy(source_key="github-models", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        catalog = json.loads(body)
        if not isinstance(catalog, list):
            raise ValueError("GitHub Models catalog must be a JSON list")

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
        for model in catalog:
            if not isinstance(model, dict) or not isinstance(model_id := model.get("id"), str) or not model_id:
                continue
            limits = model.get("limits")
            if not isinstance(limits, dict):
                limits = {}
            modalities = _string_list(model.get("supported_input_modalities")) + _string_list(
                model.get("supported_output_modalities")
            )
            records.append(
                ProviderOfferingRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    source_model_id=model_id,
                    service_id="github-models",
                    source_provider_label="GitHub Models",
                    availability_state="available",
                    modalities=list(dict.fromkeys(modalities)),
                    context_window_tokens=_positive_int(limits.get("max_input_tokens")),
                    max_output_tokens=_positive_int(limits.get("max_output_tokens")),
                    observed_at=observed_at,
                )
            )
        return records
