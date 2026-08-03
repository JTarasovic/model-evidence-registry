"""OpenAI Codex's public, product-specific model documentation connector."""

from __future__ import annotations

import re

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

CODEX_MODELS_URL = "https://learn.chatgpt.com/docs/models.md"
_MODEL_DETAILS_RE = re.compile(r"<ModelDetails\b[\s\S]*?/>", re.IGNORECASE)
_SLUG_RE = re.compile(r'\bslug="([^"]+)"')
_CODEX_SURFACE_RE = re.compile(
    r'\{\s*title:\s*"Codex (?:CLI|IDE extension|cloud)"\s*,\s*value:\s*true\s*\}', re.IGNORECASE
)


class OpenAICodexDocsConnector:
    """Parse documented Codex-accessible model slugs without consulting the API catalogue."""

    source_id = "openai-codex-docs"
    fixture_filename = "openai-codex-docs.md"
    url = CODEX_MODELS_URL
    license = "OpenAI documentation terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    fetch_policy = FetchPolicy(source_key="openai-docs", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        text = body.decode("utf-8")
        model_ids = sorted(
            {
                slug_match.group(1)
                for details in _MODEL_DETAILS_RE.findall(text)
                if _CODEX_SURFACE_RE.search(details)
                if (slug_match := _SLUG_RE.search(details)) is not None
            }
        )
        if not model_ids:
            raise ValueError("OpenAI Codex models document contains no Codex-accessible model details")

        return [
            DocumentRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                url=self.url,
                kind="product_doc",
                content_sha256=sha256_hex(body),
                retrieved_at=observed_at,
                redistribution_policy="hash_and_facts_only",
            ),
            *(
                ProviderOfferingRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    source_model_id=model_id,
                    service_id="openai-codex",
                    source_provider_label="OpenAI",
                    availability_state="available",
                    observed_at=observed_at,
                )
                for model_id in model_ids
            ),
        ]
