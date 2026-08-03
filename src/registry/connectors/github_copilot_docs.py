"""GitHub Copilot's official, public model-catalog documentation connector.

This is intentionally separate from :mod:`registry.connectors.github_models`: GitHub Models is
a distinct API/playground product, while this document describes models offered by GitHub Copilot.
The page publishes presentation names rather than a separate machine-readable Copilot model id, so
those names are retained verbatim as the source-native identifiers.
"""

from __future__ import annotations

import re

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

COPILOT_MODELS_URL = "https://docs.github.com/en/copilot/reference/ai-models/supported-models.md"
_CATALOG_SECTION_RE = re.compile(
    r"^## Supported AI models in Copilot\s*$([\s\S]*?)(?=^## |\Z)", re.MULTILINE
)
_TABLE_ROW_RE = re.compile(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", re.MULTILINE)
_FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")


class GitHubCopilotDocsConnector:
    """Parse Copilot's documented product-wide model catalogue."""

    source_id = "github-copilot-docs"
    fixture_filename = "github-copilot-docs.md"
    url = COPILOT_MODELS_URL
    license = "GitHub documentation terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    fetch_policy = FetchPolicy(source_key="github-docs", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        text = body.decode("utf-8")
        section_match = _CATALOG_SECTION_RE.search(text)
        if section_match is None:
            raise ValueError("GitHub Copilot models document has no catalogue section")

        offerings: list[ProviderOfferingRecord] = []
        for model_name, provider, release_status in _TABLE_ROW_RE.findall(section_match.group(1)):
            model_name = _FOOTNOTE_RE.sub("", model_name).strip()
            provider = provider.strip()
            if not model_name or model_name == "Model name" or set(model_name) == {"-"}:
                continue
            if not provider or provider == "Provider" or set(provider) == {"-"}:
                continue
            # The table says these models are available in Copilot. Plan, client, and organization
            # policy restrictions remain documented constraints, not a claim about any one account.
            if release_status.strip() not in {"GA", "Public preview"}:
                continue
            offerings.append(
                ProviderOfferingRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    source_model_id=model_name,
                    service_id="github-copilot",
                    source_provider_label=provider,
                    availability_state="available",
                    observed_at=observed_at,
                )
            )

        if not offerings:
            raise ValueError("GitHub Copilot models document contains no supported model rows")
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
            *offerings,
        ]
