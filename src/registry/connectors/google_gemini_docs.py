"""Google's official Gemini API Models documentation connector.

The public Models page is used instead of ``GET /v1beta/models``, which requires an API
key. The connector records the source-native model IDs from the official model cards,
along with the page hash and Google-supplied "Last updated" revision. It does not bundle
or re-host Google documentation.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODELS_INDEX_URL = "https://ai.google.dev/gemini-api/docs/models"
_MODEL_PATH_RE = re.compile(r"^/gemini-api/docs/models/([^/]+)$")
_LAST_UPDATED_RE = re.compile(r"\bLast updated\s+([^<.]+?)(?:\.|\s*<)", re.IGNORECASE)


class _ModelsPageParser(HTMLParser):
    """Collect links from the current Gemini model-card grid."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.model_ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return

        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        href = attributes.get("href")
        if href is None or not any(class_name.startswith("gemini-card") for class_name in classes):
            return

        parsed = urlsplit(href)
        if parsed.netloc not in {"", "ai.google.dev"}:
            return
        match = _MODEL_PATH_RE.fullmatch(parsed.path)
        if match:
            self.model_ids.add(match.group(1))


class GoogleGeminiDocsConnector:
    """Parse direct Gemini API model IDs from Google's public Models page."""

    source_id = "google-gemini-model-docs"
    fixture_filename = "google-gemini-model-docs.html"
    url = MODELS_INDEX_URL
    license = "Google Terms of Service; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    # Google documentation endpoints deliberately share a conservative provider-wide rate limit.
    fetch_policy = FetchPolicy(source_key="google-ai-docs", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        text = body.decode("utf-8")
        parser = _ModelsPageParser()
        parser.feed(text)
        parser.close()

        revision_match = _LAST_UPDATED_RE.search(text)
        records: list[Record] = [
            DocumentRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                url=self.url,
                kind="api_doc",
                revision=revision_match.group(1).strip() if revision_match else None,
                content_sha256=sha256_hex(body),
                retrieved_at=observed_at,
                redistribution_policy="hash_and_facts_only",
            )
        ]
        records.extend(
            ProviderOfferingRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                model_id=model_id,
                provider="Google",
                availability_state="available",
                observed_at=observed_at,
            )
            for model_id in sorted(parser.model_ids)
        )
        return records
