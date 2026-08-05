"""GitHub Copilot's official, public model-catalog documentation connector.

This is intentionally scoped to GitHub Copilot's model catalog, distinct from the retired GitHub
Models API/playground product; this document describes models offered by GitHub Copilot.
The page publishes presentation names rather than a separate machine-readable Copilot model id, so
those names are retained verbatim as the source-native identifiers.
"""

from __future__ import annotations

import re

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

COPILOT_MODELS_URL = "https://docs.github.com/en/copilot/reference/ai-models/supported-models.md"
_CATALOG_SECTION_RE = re.compile(r"^## Supported AI models in Copilot\s*$([\s\S]*?)(?=^## |\Z)", re.MULTILINE)
# A separate "Models with extended capabilities" table marks a "Configurable reasoning" column per
# model with a Supported / Not supported octicon. It covers only the latest models, so absence from
# it leaves reasoning undocumented (None) rather than a documented negative.
_EXTENDED_SECTION_RE = re.compile(r"^## Models with extended capabilities\s*$([\s\S]*?)(?=^## |\Z)", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", re.MULTILINE)
_FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")


def _reasoning_from_cell(cell: str) -> bool | None:
    """Read a "Configurable reasoning" octicon: its aria-label is the documented Yes/No."""
    if 'aria-label="Supported"' in cell:
        return True
    if 'aria-label="Not supported"' in cell:
        return False
    return None


def _extended_reasoning(text: str) -> dict[str, bool | None]:
    section_match = _EXTENDED_SECTION_RE.search(text)
    if section_match is None:
        return {}
    reasoning_by_name: dict[str, bool | None] = {}
    for model_name, _context_cell, reasoning_cell in _TABLE_ROW_RE.findall(section_match.group(1)):
        model_name = _FOOTNOTE_RE.sub("", model_name).strip()
        if not model_name or model_name == "Model" or set(model_name) == {"-"}:
            continue
        reasoning_by_name[model_name] = _reasoning_from_cell(reasoning_cell)
    return reasoning_by_name


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

        reasoning_by_name = _extended_reasoning(text)
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
                    reasoning=reasoning_by_name.get(model_name),
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
