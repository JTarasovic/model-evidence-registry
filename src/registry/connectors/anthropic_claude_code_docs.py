"""Anthropic Claude Code product documentation connector.

The public configuration document lists Claude Code model identifiers separately from the
Anthropic API catalogue. Subscription-plan and account limits are deliberately not flattened into
universal per-model availability claims.
"""

from __future__ import annotations

import html
import re

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

CLAUDE_CODE_MODELS_URL = "https://support.anthropic.com/en/articles/11940350-claude-code-model-configuration"
_SUPPORTED_MODELS_SECTION_RE = re.compile(
    r"<h2\b[^>]*>\s*Supported models\s*</h2>(?P<section>[\s\S]*?)(?=<h2\b|\Z)", re.IGNORECASE
)
_CODE_RE = re.compile(r"<code\b[^>]*>([\s\S]*?)</code>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


class AnthropicClaudeCodeDocsConnector:
    """Parse the official Claude Code supported-model identifiers."""

    source_id = "anthropic-claude-code-docs"
    fixture_filename = "anthropic-claude-code-docs.html"
    url = CLAUDE_CODE_MODELS_URL
    license = "Anthropic documentation terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    fetch_policy = FetchPolicy(source_key="anthropic-docs", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        text = body.decode("utf-8")
        section_match = _SUPPORTED_MODELS_SECTION_RE.search(text)
        if section_match is None:
            raise ValueError("Anthropic Claude Code document has no supported-models section")
        model_ids = sorted(
            {
                html.unescape(_TAG_RE.sub("", model_id)).strip()
                for model_id in _CODE_RE.findall(section_match.group("section"))
                if html.unescape(_TAG_RE.sub("", model_id)).strip()
            }
        )
        if not model_ids:
            raise ValueError("Anthropic Claude Code document contains no supported model identifiers")

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
                    service_id="anthropic-claude-code",
                    source_provider_label="Anthropic",
                    availability_state="available",
                    observed_at=observed_at,
                )
                for model_id in model_ids
            ),
        ]
