"""Configured Hugging Face official model-card connector.

The Hub model-info API supplies a model repository's immutable revision and card metadata without
requiring a token.  This connector deliberately fetches only the official repositories required by
the consumer inventory; it is not a broad crawl of the Hub.  Each response becomes a separate
hash-and-facts-only ``DocumentRecord`` plus an offering for the Hub-hosted weights.
"""

from __future__ import annotations

import json

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODEL_REPOSITORIES = (
    "nvidia/Nemotron-3-Ultra-550B-A55B",
    "nvidia/Nemotron-3-Super-120B-A12B",
    "nvidia/Nemotron-3-Nano-30B-A3B",
    "nvidia/Nemotron-Nano-9B-v2",
    "nvidia/Nemotron-3.5-Content-Safety",
    "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16",
    "nvidia/Nemotron-Nano-12B-v2-VL",
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen3.6-27B",
    "Qwen/Qwen2.5-Coder-7B-Instruct",
    "deepseek-ai/DeepSeek-R1-0528",
    "zai-org/GLM-4.7",
    "inclusionAI/Ling-3.0-Flash",
    "google/gemma-4-31B-it",
    "google/gemma-4-26B-A4B-it",
)


def model_info_url(repository: str) -> str:
    """Return the public Hub API URL for one configured source-native repository ID."""
    return f"https://huggingface.co/api/models/{repository}"


MODEL_INFO_URLS = tuple(model_info_url(repository) for repository in MODEL_REPOSITORIES)
FIXTURE_FILENAMES = {
    url: f"hf-model-card-{index:02d}.json" for index, url in enumerate(MODEL_INFO_URLS, start=1)
}


class HfModelCardsConnector:
    """Parse configured official Hugging Face model-card metadata responses."""

    source_id = "hf-model-cards"
    # ``url`` keeps the original Connector contract intact; ``urls`` declares the finite card set.
    url = MODEL_INFO_URLS[0]
    urls = MODEL_INFO_URLS
    fixture_filenames = FIXTURE_FILENAMES
    license = "Hugging Face Hub and cardholder terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    fetch_policy = FetchPolicy(source_key="huggingface.co", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        model = json.loads(body)
        if not isinstance(model, dict) or not isinstance(model_id := model.get("id"), str) or not model_id:
            raise ValueError("Hugging Face model-info response must contain a non-empty id")
        revision = model.get("sha")
        if revision is not None and not isinstance(revision, str):
            raise ValueError("Hugging Face model-info sha must be a string when present")
        card_data = model.get("cardData")
        if card_data is not None and not isinstance(card_data, dict):
            raise ValueError("Hugging Face model-info cardData must be an object when present")

        return [
            DocumentRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                url=model_info_url(model_id),
                kind="model_card",
                revision=revision,
                content_sha256=sha256_hex(body),
                retrieved_at=observed_at,
                redistribution_policy="hash_and_facts_only",
            ),
            ProviderOfferingRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                source_model_id=model_id,
                # A model card is a Hub listing, not a registry-owned inference/access service, so
                # ``service_id`` stays null; the Hub is recorded only as the verbatim source provider.
                service_id=None,
                source_provider_label="Hugging Face Hub",
                availability_state="unavailable" if model.get("disabled") is True else "available",
                observed_at=observed_at,
            ),
        ]
